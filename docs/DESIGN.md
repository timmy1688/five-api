# 产品范围、权限与管理 API

## 范围

轻量多租户 AI 网关：平台开户、分配额度、管理渠道和售价；租户只管理自己的 API Key，按实际服务渠道计费。开通、调额和收款走人工与线下流程。

不做：动态角色与权限勾选、组织/成员多层级、SSO、在线支付、租户删除/合并/转移、自助导出、上游成本与毛利核算、Helm 等多套部署方式。Key 更换通过新建、替换应用配置、撤销旧 Key 完成。

## 角色与凭证

| 身份 | 能力 |
| --- | --- |
| 平台管理员 | 创建租户账号，设置售价、渠道、额度、共享限流和模型范围，管理平台配置与异常；可停用或撤销客户 Key，可创建平台自用 Key |
| 租户账号 | 修改本人密码，创建、限制、停用、撤销自己的 Key，查看自己的用量和费用；不能创建账号 |
| 推理 Key | 只调用授权模型的推理接口，不能访问后台或创建 Key |

- 一个租户一个账号。角色和账号的 tenant_id 创建后不可改；客户业务启停只有 Tenant.is_enabled 一个入口。
- 管理员自用 Key 自动归内部 is_system 空间，不出现在客户列表；不提供管理员代客户建 Key 的入口。
- 管理接口用密码登录换取 JWT（默认 60 分钟，`JWT_EXPIRE_MINUTES` 可改，aud 固定 five-api-management），无刷新令牌和长期管理 Token。每次请求从数据库读取角色、状态和 token_version，JWT 里自行添加的 role、tenant_id 无效；改密或平台重置密码撤销旧 JWT，临时密码首次登录必须修改。
- 推理 Key 随机生成，数据库只存 SHA-256 摘要和前缀，明文只在创建响应中出现一次（no-store），前端关闭后清除。JWT 不能调用推理接口，推理 Key 不能访问管理接口。
- 上游凭据用 ENCRYPTION_KEY 加密，JWT 用 SECRET_KEY 签名，两者分开且不存数据库，见 [运维文档](OPERATIONS.md)。

## 额度与限流

- 租户额度是累计美元上限，新租户默认 0、不自动重置；只有平台能调整，调整需带 reason 和 UUID operation_id，同一 ID 重试幂等，内容不同返回 409，不能调到低于已用加占用。
- 多个 Key 共享租户总额，Key 上限 -1 表示不另设，不会增加租户余额；撤销、新建 Key 不清空已用金额。
- 新租户默认共享 120 RPM、100,000 TPM、10 并发，可设正数或 -1 不限；Key 可设更严的限制，仍受租户限制。每个租户默认最多 100 把未撤销 Key，创建限频 20 次/分钟。
- 请求按内部 UUID 足额预占，报价快照固定；用量、Key 与租户扣费、日志、日汇总在一个事务提交，重试不重复扣费。失败和未知结果继续占用，等待核对。估算偏差和上游未知结果不保证绝对零超额。

## 查询边界

- 所有租户查询在服务端限定归属，跨租户详情返回 404；视频查询、下载和历史任务同样先校验 Key 归属。
- 租户只有 Key 页和改密入口。模型广场、价格、巡检和平台日志只对管理员开放。
- 租户经 `GET /api/keys/channels` 只看到可用渠道的名称、倍率、模型价格和健康状态，不含上游地址与密钥。
- 日志、错误、告警中的已知凭据都会脱敏。只记录必要的管理事件：开户、额度、Key、价格、渠道、设置和异常处理。

## 管理 API

开发环境后端 `http://127.0.0.1:5002`。登录后用 `Authorization: Bearer <access_token>` 调用。

| 接口 | 说明 |
| --- | --- |
| `POST /api/login` | username、password，返回 access_token、expires_in、must_change_password |
| `GET /api/me` | 当前账号、角色、tenant_id 和是否需要改密 |
| `PUT /api/password` | old_password、new_password，返回新 JWT，旧 JWT 失效 |
| `POST /api/tenants` | 仅平台；创建租户及其账号，初始额度 0 |
| `PUT /api/tenants/{id}` | 仅平台；名称、启停、模型范围、Key 数量上限、共享限流 |
| `PUT /api/tenants/{id}/quota` | 仅平台；调整累计上限，须带 reason 和 operation_id |
| `PUT /api/tenants/{id}/password` | 仅平台；设置临时密码并撤销旧 JWT |
| `POST /api/keys` | 租户建自己的 Key；平台建平台自用 Key；归属由服务端决定 |
| `GET /api/keys`、`/api/keys/{id}` | 租户只能看到自己的 Key；从不返回已有明文 |
| `GET /api/keys/summary` | 当前租户总额度、已用、占用与可用 |
| `PUT /api/keys/{id}` | 租户可改 name、quota_total、allowed_models、expires_at、allowed_ips、rpm/tpm/并发限制、channel_ids、is_enabled |
| `DELETE /api/keys/{id}` | 永久撤销，保留费用历史，不能再启用 |
| `GET /api/keys/{id}/usage` | 最近 50 条请求元数据，不含正文和凭据 |

- 新密码 8 个字符到 72 个 UTF-8 字节；临时密码改密前只能访问本人资料和改密。
- 建 Key 超时不要自动重发：先查列表确认，找不回明文就撤销后重建。
- 401：凭证缺失、过期或已撤销；403：租户访问平台接口；422：提交了不允许的字段；404：授权范围外的资源。推理接口返回 OpenAI/Anthropic 原生错误格式。

```python
import httpx
from getpass import getpass

with httpx.Client(base_url="http://127.0.0.1:5002", trust_env=False) as client:
    login = client.post("/api/login", json={"username": input("Username: "), "password": getpass()})
    login.raise_for_status()
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    created = client.post("/api/keys", json={"name": "my-application", "quota_total": 10})
    created.raise_for_status()
    key = created.json()["key"]  # Store in the application's secret config; it is shown only once.
```
