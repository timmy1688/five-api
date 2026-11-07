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

- 租户额度是累计美元上限，新租户默认 0、不自动重置；只有平台能调整，调整需带 UUID operation_id（reason 选填），同一 ID 重试幂等，内容不同返回 409，不能调到低于已用加占用。
- 多个 Key 共享租户总额，Key 上限 -1 表示不另设，不会增加租户余额；撤销、新建 Key 不清空已用金额。
- 新租户默认共享 120 RPM、100,000 TPM、10 并发，可设正数或 -1 不限；Key 可设更严的限制，仍受租户限制。每个租户默认最多 100 把未撤销 Key，创建限频 20 次/分钟。
- 请求按内部 UUID 足额预占，报价快照固定；用量、Key 与租户扣费、日志、日汇总在一个事务提交，重试不重复扣费。失败和未知结果继续占用，等待核对。估算偏差和上游未知结果不保证绝对零超额。

## 查询边界

- 所有租户查询在服务端限定归属，跨租户详情返回 404；视频查询、下载和历史任务同样先校验 Key 归属。
- 租户只有 Key 页和改密入口。模型广场、价格、巡检和平台日志只对管理员开放。
- 租户经 `GET /api/keys/channels` 只看到可用渠道的名称、倍率、模型价格和健康状态，不含上游地址与密钥。
- 日志、错误、告警中的已知凭据都会脱敏；审计内容存库前把扫描命中的密钥替换为 `[REDACTED:类型]`。转发给租户的上游错误另外隐去平台的上游组织、项目编号和限流额度，管理员日志保留原文。只记录必要的管理事件：开户、额度、Key、价格、渠道、设置和异常处理。

## 流式与模型巡检

- 只在流式首包前切换渠道；首包后断流不重放已发出的回答。显式零用量与缺失用量分开处理，缺失字段估算并标明 `usage_source`，不承诺与厂商账单完全一致。
- 有效结束信号：Chat 的 `[DONE]` 或所有 choice 的 `finish_reason`，Responses 的 `response.completed` / `response.incomplete`，Anthropic 的 `message_stop`。缺少结束信号的 EOF 记为 `stream_incomplete`，有输出的按已知用量或估算结算，不跨渠道重放；完全没有事件的未知结果继续占用额度供核对。
- Responses `response.failed`、Chat / Anthropic 流内 `error` 记为渠道失败。SSE 已建立时客户端 HTTP 状态可能仍是 200，日志的 `status_code` 表示实际结果，`upstream_status_code` 保留上游的 200；原生错误事件脱敏后只转发一次。
- 健康巡检调用实际文本推理接口，默认 900 秒；GPT/Claude 降智参考默认 86400 秒，用指令遵循、合成计算和强制工具参数检查，带随机标记减少缓存影响，保留每次证据和套件版本。全局最多两个并发。它只是小规模回归信号，不能鉴定真实型号，也不替代业务评测；非文本模型不参与。

## 管理 API

开发环境后端 `http://127.0.0.1:5002`。登录后用 `Authorization: Bearer <access_token>` 调用。

| 接口 | 说明 |
| --- | --- |
| `POST /api/login` | username、password，返回 access_token、expires_in、must_change_password |
| `GET /api/me` | 当前账号、角色、tenant_id 和是否需要改密 |
| `PUT /api/password` | old_password、new_password，返回新 JWT，旧 JWT 失效 |
| `POST /api/tenants` | 仅平台；创建租户及其账号，初始额度 0。只需 `username`，`name` 省略时与用户名相同，控制台不再单独填写名称。不传 `password` 时服务端生成一次性临时密码，只在本次响应的 `temporary_password` 中返回（no-store） |
| `POST /api/users`、`PUT /api/users/{id}/password` | 仅平台；创建平台管理员、重置其密码。密码规则和 `temporary_password` 返回方式与租户相同 |
| `PUT /api/tenants/{id}` | 仅平台；说明、启停、模型范围、Key 数量上限、共享限流（接口仍接受 `name`，控制台不再提供） |
| `PUT /api/tenants/{id}/quota` | 仅平台；设置累计上限，须带 operation_id，`reason` 选填；前后金额一律写入审计事件。控制台提供“增加 / 减少 / 设为总额”，提交前读取最新额度并检查不低于已用加占用 |
| `PUT /api/tenants/{id}/password` | 仅平台；重置为临时密码（默认由服务端生成并一次性返回）并撤销旧 JWT |
| `POST /api/keys` | 租户建自己的 Key；平台建平台自用 Key；归属由服务端决定 |
| `GET /api/keys`、`/api/keys/{id}` | 租户只能看到自己的 Key；从不返回已有明文 |
| `GET /api/keys/summary` | 当前租户总额度、已用、占用与可用 |
| `PUT /api/keys/{id}` | 租户可改 name、quota_total、allowed_models、expires_at、allowed_ips、rpm/tpm/并发限制、channel_ids、is_enabled |
| `DELETE /api/keys/{id}` | 永久撤销，保留费用历史，不能再启用 |
| `GET /api/keys/{id}/usage` | 最近 50 条请求元数据，不含正文和凭据 |
| `POST /api/channels/{id}/test` | 仅平台；传 `{"model":"渠道内模型名"}`，分别检测模型列表、原生生成和流式接口；不传请求体时检测第一个配置模型 |

渠道检测返回 `model`、`actual_model` 和 `checks`：每项含 `kind`、`status`（passed / failed / timeout / skipped）、`status_code`、`latency_ms`、`first_text_ms`、脱敏 `error`、可选 `skip_reason`。OpenAI 渠道检测 models、chat、chat_stream、responses、responses_stream；Anthropic 渠道检测 models、messages、messages_stream。顶层 `success` 在至少有一项非跳过检查且所有非跳过项目通过时为 true，某一接口失败不代表其他接口不可用。

Anthropic 兼容渠道可能只提供 Messages 接口，模型列表返回 HTTP 404 / 405 时将该项标为 `skipped`、`skip_reason=models_endpoint_unavailable`，保留原始 HTTP 状态，并从整体判定和通过率分母中排除。401 / 403、429、5xx、超时及格式错误仍为失败；OpenAI 渠道不使用此跳过规则。

检测使用渠道内一个可用上游 Key，发起少量真实文本请求，会产生上游费用；不做跨渠道重试，不计入客户账单，也不修改熔断状态。每项最多 15 秒，共享巡检的全局两个并发、管理员每分钟 6 次限制；同一渠道模型的连接检测不能重复运行（409）。暂不检测图片、音频、视频和向量模型。

- 新密码至少 12 个字符、不超过 72 个 UTF-8 字节，并在小写、大写、数字、符号中混用至少三类；只约束正在设置的密码，登录和旧密码校验不受影响，已有账号不用改。
- 管理后台不再让管理员手输别人的密码：创建账号和重置密码默认由服务端生成 19 位一次性临时密码（排除易混字符），只在响应中出现一次，页面关闭即清除，审计事件只记录是否为生成，不记录密码。API 仍可显式传 `password`，须满足上述规则。
- 临时密码改密前只能访问本人资料和改密。
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
