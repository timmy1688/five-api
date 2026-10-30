# Key 管理 API

MVP 使用账号密码登录换取短期 JWT，再用 `Authorization: Bearer <access_token>` 管理 Key。网页与程序共用这一条认证路径。账号密码只用于登录和改密，不逐次传给 Key 接口；不新增长期管理 Token、PAT、OAuth 或动态权限配置。

推理使用的 `sk-...` Key 不能访问管理 API；管理 JWT 不能调用推理接口。平台和租户的身份、归属、启用状态在每次请求时从数据库读取，JWT 中自行添加 role 或 tenant_id 不能改变权限。

## 选择依据

| 方式 | MVP 决定 | 原因 |
| --- | --- | --- |
| 每次操作都提交账号密码或 Basic Auth | 不采用 | 扩大密码使用范围，难以撤销单次泄露的访问凭证 |
| 登录后使用短期管理 JWT | 采用 | 复用现有密码、登录限频、改密撤销和固定角色检查 |
| 长期管理 Token / PAT | 延后 | 当前一个租户一个账号，无需增加长期凭证的创建、展示、过期和撤销流程 |
| 复用推理 Key 管理其他 Key | 不采用 | 应用持有推理凭证时，不应同时获得创建新凭证的权限 |

参考 [LiteLLM 虚拟 Key](https://docs.litellm.ai/docs/proxy/virtual_keys) 与 [RBAC](https://docs.litellm.ai/docs/proxy/access_control) 的身份和资源边界，Five API 在 MVP 中明确分开管理凭证与推理凭证。

管理 JWT 默认 60 分钟，响应含 `expires_in`，可用 `JWT_EXPIRE_MINUTES` 配置。过期后重新登录，没有刷新令牌。修改密码或平台重置密码会递增 token_version，撤销该账号以前签发的全部登录令牌。网页退出只清除浏览器中的令牌，不声称在服务端撤销所有会话。

无人值守程序需要安全保存账号密码，以便过期后重新登录。如果后续明确需要长期、免密码续期的自动化接入，再增加独立可撤销、固定用途的管理 PAT。

## 接口

开发环境后端为 `http://127.0.0.1:5002`，前端为 `http://127.0.0.1:5001`。部署与外置主密钥见 [运维文档](OPERATIONS.md)。

| 接口 | 身份与行为 |
| --- | --- |
| `POST /api/login` | JSON username、password，返回 access_token、token_type、expires_in、must_change_password |
| `GET /api/me` | 当前账号 id、username、固定 role、tenant_id 和首次改密状态 |
| `PUT /api/password` | old_password、new_password，返回新 JWT；原 JWT 失效 |
| `POST /api/tenants` | 仅平台；一次事务创建租户及唯一账号，初始额度默认 0 |
| `PUT /api/tenants/{id}` | 仅平台；名称、说明、启停、模型范围、Key 数量上限、共享 RPM/TPM/并发 |
| `PUT /api/tenants/{id}/quota` | 仅平台；调整累计总上限，须带 reason 和 UUID operation_id |
| `PUT /api/tenants/{id}/password` | 仅平台；设置临时密码并撤销旧 JWT，账号下次登录须改密 |
| `POST /api/keys` | 租户创建自己的 Key；平台管理员创建平台自用 Key，均由服务端确定归属 |
| `GET /api/keys` | 租户仅自己的 Key；平台可查询全局或用 tenant_id 筛选 |
| `GET /api/keys/summary` | 当前租户的总额度、已用、占用与可用 |
| `GET /api/keys/{id}` | 读取授权范围内的 Key，始终不返回既有明文 |
| `PUT /api/keys/{id}` | 更新授权范围内的 Key；租户和平台使用不同字段允许清单 |
| `DELETE /api/keys/{id}` | 永久撤销，保留 Key 与费用历史，不能再启用 |
| `GET /api/keys/{id}/usage` | 最近 50 条请求元数据，无正文、上游底价和凭据 |

临时密码或公共默认密码登录后，改密前只允许本人资料和改密。新密码至少 8 个字符，最多 72 个 UTF-8 字节，以避免 bcrypt 静默截断。

租户 Key 可写字段为 name、quota_total、allowed_models、expires_at、allowed_ips、rpm_limit、tpm_limit、concurrent_limit；更新时还可设置 is_enabled。quota_total=-1 表示不另设 Key 上限，仍共享租户预算。模型列表为空时继承租户范围；平台模型组与 Key 模型限制同时生效。不能修改 role、tenant_id、quota_used、报价、周期、审计策略或模型组。

每个租户默认最多保留 100 把未撤销 Key，创建限频 20 次/分钟。已停用但未撤销的 Key 仍计入数量。撤销并新建不会减少租户已用额度。

## 程序接入示例

以下示例在已安装 httpx 的开发虚拟环境运行。首次改密和 Token 过期由程序显式处理；请将新 Key 交付给受控应用配置，明文关闭后无法再次查询。

```python
from getpass import getpass
import httpx

with httpx.Client(base_url="http://127.0.0.1:5002", trust_env=False) as client:
    username = input("Username: ")
    password = getpass("Password: ")
    login = client.post("/api/login", json={"username": username, "password": password})
    login.raise_for_status()
    session = login.json()
    client.headers["Authorization"] = "Bearer " + session["access_token"]

    if session["must_change_password"]:
        changed = client.put("/api/password", json={
            "old_password": password,
            "new_password": getpass("New password: "),
        })
        changed.raise_for_status()
        client.headers["Authorization"] = "Bearer " + changed.json()["access_token"]

    created = client.post("/api/keys", json={
        "name": "my-application",
        "quota_total": 10,
    })
    created.raise_for_status()
    result = created.json()
    # 将 result["key"] 写入受控应用配置，不放进日志。
    print("Created key id:", result["id"])
```

创建响应设置 `Cache-Control: no-store`。网络超时后不要自动重放建 Key 请求：先查询列表确认结果，无法找回已创建明文时撤销该 Key，再创建替代 Key。额度调整使用同一个 operation_id 重试；同一 ID 搭配不同金额或原因返回 409。

缺失、过期或撤销的管理凭证返回 401；租户访问平台入口或越权字段分别返回 403、422；授权范围外的 Key 详情、更新、撤销和用量返回 404。推理接口使用协议原生错误；持久化结算、异常入口与恢复步骤见运维文档。
