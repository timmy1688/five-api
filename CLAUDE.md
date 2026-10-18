# CLAUDE.md — Five API 开发指南

Five API 是自托管 AI 网关：对外提供 OpenAI 兼容接口（`/v1/*`）和 Anthropic 接口（`/v1/messages`），按线协议原样透传到上游渠道，附带 Vue 3 管理后台。部署和使用见 [README.md](README.md)。

**技术栈**：FastAPI + Tortoise ORM + MySQL 8 + Redis 7（`backend/`）｜Vue 3 + Element Plus + ECharts（`frontend/`）｜单镜像 Docker Compose。

## 常用命令

```bash
./service.sh install            # 建根目录 .venv，装前后端依赖；依赖变了重跑
./service.sh start|stop|logs    # 前端 :5001，后端 :5002，Vite 把 /api、/v1 代理到后端
cd backend && ../.venv/bin/pytest -q -p no:warnings          # 全量测试
cd backend && ../.venv/bin/aerich migrate --name describe_change   # 改了模型后生成迁移，检查后提交
cd frontend && npx vue-tsc --noEmit && npx vite build
docker compose build gateway && docker compose up -d --no-build   # 重建生产容器
```

- 本机设了 `http_proxy` 时，访问本地服务要带 `--noproxy '*'` 或设 `NO_PROXY`。
- 默认管理员 `admin` / `admin123`，首次登录必须改密码；用默认密码拿到的 token 访问受权限保护的接口一律 403 `Password change required`。
- `SECRET_KEY`（至少 32 位）必填，加密渠道 Key 并签发 JWT，没设置拒绝启动。网关容器无挂载；Compose 从根目录 `.env` 取，`service.sh start` 缺失时自动生成。测试在 `conftest.py` 里设了固定值。

## 目录与分层

| 目录 | 职责 |
|---|---|
| `app/routers/` | 薄层：解析请求、定义 `send_fn` / `stream_fn` 闭包、调服务。`openai_proxy.py`、`anthropic_proxy.py` 是代理入口，其余是 `/api/*` 管理接口 |
| `app/services/` | 业务逻辑：`routing.py` 选路、`proxy.py` 故障转移编排与计费、`pre_checks.py` 前置检查、`quota.py` 预留与扣费、`pricing.py` 计价与内置价格表、`auth.py` 认证与 RBAC，其余按文件名对应功能 |
| `app/providers/` | 上游适配：`base.py` 共享连接池、号池选 Key、`raise_for_error_body`；`openai_provider.py`、`anthropic_provider.py`；`registry.py` 候选渠道排序 |
| `app/models/`、`app/schemas/` | Tortoise 模型和 Pydantic 模型，字段说明以代码为准 |
| `migrations/` | aerich 迁移，启动时 `aerich upgrade` |
| `frontend/src/config/navigation.ts` | 页面、标题、菜单权限的唯一来源 |

## 请求管线

1. `X-Request-ID` 中间件。
2. `verify_api_key`：SHA-256 查表，检查启用、过期、IP 白名单。
3. `run_pre_checks()`：配额、模型权限、RPM。新增前置策略加在这里，所有代理路由自动生效。
4. `plan_route()`：会话粘性、预算降级目标 → `resolve_with_fallbacks()` → `resolve_candidates()`。只保留与入口协议一致的渠道，按 priority 分层，层内按系统设置 `routing_strategy` 排序（`weighted` / `least_busy` / `latency`），粘性渠道健康时提到最前。
5. `begin_request_budget()` 按估算费用预留额度（Key、团队、滚动窗口、TPM），`concurrency_limiter.acquire()` 取并发租约。
6. `execute_with_failover` / `stream_with_failover` 依次尝试候选。
7. `_bill_and_log()`：结算、写日志、更新 `usage_daily`、释放预留和并发。

## 协议

渠道 `provider` 是**线协议**，不是厂商：`openai`（OpenAI 及所有兼容端点，含 Gemini、千问、DeepSeek、vLLM）或 `anthropic`（Anthropic 原生及兼容端点，如 `https://api.deepseek.com/anthropic`）。

- `/v1/messages`、`/v1/messages/count_tokens` 只选 anthropic 渠道，其余 `/v1/*` 只选 openai 渠道。网关不做格式转换，另一协议的渠道不参与故障转移。
- 两种都是透传：只按 `model_mapping` 改模型名，流式 chat/completions 补 `stream_options.include_usage`。OpenAI 路由用 `model_dump(exclude_unset=True)`，没传的字段不发给上游。
- Provider 把上游的 `x-ratelimit-*`、`anthropic-ratelimit-*`、`retry-after(-ms)`、`request-id` 带回客户端，`x-request-id` 改名 `x-upstream-request-id`。流式由 `open_stream()` 先取首段再发响应头。
- 新的原生协议才需要新适配器：继承 `BaseProvider`，在 `registry.py` 的 `PROVIDER_MAP` 注册并归入对应协议族。

## 故障转移与可用性

- 可重试：超时、网络错误、`RemoteProtocolError`、上游 5xx。4xx 不切换、不计熔断。流式只在首包前切换。
- 上游 HTTP 200 但 JSON 正文只有 `error`（New API 等中转常见）：`raise_for_error_body()` 按 `error.type` 映射为 400/401/403/404/429，其余记 502 可切换；正文原样返回，日志 `upstream_status_code` 记 200。流式收到 JSON 时同样处理。
- 上游 4xx 且正文是 JSON 时原样返回客户端；5xx、超时、非 JSON 报错统一 502，消息不带上游地址（`error_detail.client_message`）。
- 熔断：连续失败达阈值后标记，后台探测恢复；全部熔断时仍尝试一个最高优先级渠道。
- 号池：渠道 `api_key` 存多把 Key（换行或逗号分隔）。429 按 `retry-after` 冷却（缺省 30 秒，上限 3600），401/403 冷却 600 秒，键 `five:keycool:{channel_id}:{指纹}`；有会话时按会话固定，否则轮询 `five:keyrr:{channel_id}`。渠道测试和健康探测只用第一把。
- 模型回退：系统设置 `model_fallbacks`，主模型候选之后依次接备选模型候选，日志 `model_actual` 记真实模型。备选仍受 Key 模型权限约束。
- 粘性会话：会话标识取 `X-Session-Id` / `session_id` / `session-id`（Codex）/ `X-Conversation-Id`，否则用 system + 首条 user 消息的指纹。绑定 `five:sticky:{api_key_id}:{hash}`，成功后刷新；只对含 `messages` 的请求生效。
- 客户端断开：Starlette 会取消响应任务，anyio 取消是持续生效的，所以流式清理放在 `anyio.move_on_after(30, shield=True)` 里（`proxy._UpstreamStream` 和 `stream_with_failover` 的 finally）。改这块要保留屏蔽。

## 计费

```
fresh = prompt - cache_read - cache_write
cost  = (fresh × 输入价 + cache_read × 缓存读价 + cache_write × 缓存写入价 + completion × 输出价) / 1M
      + request_units × 按次价
```

- 价格来源：渠道 `model_pricing` → 全局 `model_prices`，查价用 `model_actual`。渠道显式 0 是有效覆盖；渠道没填 `cache_write` 时写入按该渠道输入价。
- 按次价：图片按张，语音、转写、rerank 按次，视频按秒（`seconds`，默认 4）。内置价格表 `DEFAULT_MODEL_PRICES` 可带 `request` 键，改动后更新 `MODEL_PRICE_CATALOG_VERSION`。
- 预留：估算用当前最高输入价和输出价。`used + 其他预留 < total` 就放行，所以最多超支一次请求；扣减用 `F()` 原子更新。内嵌 base64 每段按 1600 token 估算。
- 流式结束仍没有 usage 时，输出按已转发文本估算（中日韩字符 1 token，其余 4 字符 1 token），输入取预留时的估算。
- 分时定价、预算降级、自动缓存、滚动限额分别在 `time_pricing.py`、`downgrade.py`、`auto_cache.py`、`spend_windows.py`，配置都存在 `system_settings`。

**用量口径（容易错）**：费用公式是 OpenAI 口径，`prompt_tokens` 含缓存。Anthropic 的 `input_tokens` 不含缓存，必须补齐：

```
prompt_tokens      = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
cached_tokens      = cache_read_input_tokens
cache_write_tokens = cache_creation_input_tokens
```

归一化在 `routers/anthropic_proxy.py` 的 `_extract_anthropic_usage`（非流式）和 `_passthrough_stream_with_usage`（流式），两处要同步改。

## 视频

`/v1/videos` 提交成功即按秒计费，Redis `five:video:{id}` 记渠道、上游 Key 指纹、所属 Key 和秒数，TTL 7 天。查询、下载、删除走 `_video_upstream` 直连原渠道和原 Key，不计费不写日志；remix 通过 `_proxy(channel_id=...)` 固定原渠道，按原秒数计费。只有创建它的 Key 能访问。

## 错误码

| 状态 | code | 原因 |
|---|---|---|
| 401 | `invalid_api_key` / `key_disabled` / `key_expired` | Key 认证失败 |
| 403 | `model_not_allowed` / `ip_not_allowed` / `team_disabled` / `Permission denied` | 模型无权限 / IP 不在白名单 / 团队停用 / 管理员无权限 |
| 404 | `model_not_found` / `video_not_found` | 没有支持该模型的渠道 / 视频不存在或不属于该 Key |
| 429 | `quota_exceeded` / `team_quota_exceeded` / `window_limit` / `team_window_limit` | 总额度或滚动限额用完 |
| 429 | `rpm_limit` / `tpm_limit` / `concurrent_limit` | 速率或并发超限 |
| 502 | `upstream_error` | 上游 5xx、超时，或 4xx 正文不是 JSON |
| 503 | `channel_unavailable` | 创建视频的渠道已不可用 |

## 开发约定

- list 接口返回 `{"total": N, "items": [...]}`，分页 `?page=1&size=20`。
- 错误响应：OpenAI 路由用 `openai_error()`，Anthropic 路由用 `anthropic_error()`。
- 认证：代理路由 `verify_api_key`；管理路由 `require_permission("资源:read|write")`；只需登录的用 `get_current_admin`。前端只做显隐，后端是唯一授权边界。
- 新权限：`services/auth.py` 的 `ALL_PERMISSIONS` 和 `BUILTIN_ROLES`（Super Admin 全部、Viewer 全部 `:read`），路由加 `require_permission`，前端用 `auth.hasPermission()`。
- 新管理页：`views/Xxx.vue` → `config/navigation.ts` 加菜单 → `router/index.ts` 的 `viewComponents` 注册。
- 新模块取 Redis 用 `from app import dependencies` + `await dependencies.get_redis()`，测试的 FakeRedis 才能替换到。
- `usage_daily` 的 MySQL upsert 用 8.0.19 起的行别名写法 `VALUES (...) AS new`。
- 加了上游 HTTP 调用的测试 mock 要覆盖 `client.request`（`send_raw` 用它）和 `client.post`。
- 函数职责单一、早返回；注释只写代码表达不了的约束。
- 用户可见的变化写进 `CHANGELOG.md`，打 `v*` tag 时发布流程读取对应段落。
