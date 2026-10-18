# CLAUDE.md — Five API Gateway 开发指南

## 项目简介

Five API 是一个自托管的 AI API 网关，对外暴露 OpenAI 兼容接口和 Anthropic 兼容接口，内部按两种线协议（OpenAI 兼容 / Anthropic）将请求路由到多个上游 LLM 提供商（OpenAI、Anthropic Claude、Google Gemini、Alibaba Qwen 等，均通过对应协议接入）。附带 Vue 3 管理后台用于渠道管理、API Key 管理、模型分组、RBAC 权限管理、用量统计和日志查看。支持 Claude Code 直连。

**技术栈**: FastAPI + Tortoise ORM + MySQL + Redis（后端）| Vue 3 + Element Plus + ECharts（前端）| Docker Compose（部署）

---

## 快速开始

### 环境要求

- Python >= 3.11、Node.js >= 20、MySQL 8.0、Redis 7+（或直接用 Docker Compose）

### Docker Compose 一键部署

```bash
cd /opt/five-api
docker compose up -d               # 不需要 .env
docker compose logs -f gateway     # 查看日志
```

启动后管理后台和 API 都在 `http://localhost`（容器内 8000，默认映射到宿主机 80），默认管理员 `admin` / `admin123`（Super Admin 角色），首次登录必须先改密码

### 本地开发

```bash
# 首次运行或依赖更新后
./service.sh install

# 方法 A：一键启动
./service.sh start      # 前端 :5001  后端 :5002
./service.sh stop       # 停止
./service.sh restart    # 重启
./service.sh status     # 查看状态
./service.sh logs       # 跟踪日志（也可指定 backend / frontend）

# 方法 B：手动启动
docker compose up -d mysql redis
cd backend && ../.venv/bin/aerich upgrade && ../.venv/bin/uvicorn app.main:app --reload --port 5002
cd frontend && npm install && npx vite --port 5001
```

`install` 会创建根目录 `.venv` 并安装后端、前端依赖。依赖文件更新后重新
执行一次即可。`start` 使用项目本地的 uvicorn 和 Vite，依赖未安装时会提示
先执行 `./service.sh install`。

前端 Vite dev server 已配置代理，`/api` 和 `/v1` 请求自动转发到 `http://127.0.0.1:5002`。

---

## 项目结构

```
/opt/five-api/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 应用入口，lifespan，中间件注册，预置角色初始化
│   │   ├── config.py                # pydantic-settings 配置 + Tortoise ORM 配置
│   │   ├── dependencies.py          # Redis 连接管理
│   │   ├── models/                  # Tortoise ORM 数据模型
│   │   │   ├── user.py              #   管理用户（role_id FK → roles）
│   │   │   ├── role.py              #   角色（permissions JSON）
│   │   │   ├── channel.py           #   上游渠道（含 model_pricing）
│   │   │   ├── api_key.py           #   API Key（SHA-256 哈希，USD 配额，model_group_id）
│   │   │   ├── model_group.py       #   模型分组（命名的模型列表，分配给 Key）
│   │   │   ├── model_price.py       #   全局模型定价（含 cached_price）
│   │   │   └── request_log.py       #   请求日志（含 cost、cached_tokens）
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   │   ├── openai.py            #   OpenAI 兼容格式
│   │   │   ├── anthropic.py         #   Anthropic 兼容格式
│   │   │   ├── user.py              #   用户相关（UserInfo/Create/Update，含 role_id、permissions）
│   │   │   ├── role.py              #   角色 CRUD
│   │   │   ├── channel.py           #   渠道 CRUD
│   │   │   ├── api_key.py           #   Key CRUD（含 model_group_id）
│   │   │   ├── model_group.py       #   模型分组 CRUD
│   │   │   ├── model_price.py       #   模型定价 CRUD
│   │   │   └── stats.py             #   统计数据
│   │   ├── providers/               # 上游提供商适配器
│   │   │   ├── base.py              #   抽象基类 BaseProvider
│   │   │   ├── openai_provider.py   #   OpenAI 协议（含所有 OpenAI 兼容端点，透传）
│   │   │   ├── anthropic_provider.py#   Anthropic 协议（原生直通 + count_tokens）
│   │   │   └── registry.py          #   渠道选择 & 模型路由（按协议过滤）
│   │   ├── services/                # 基础设施（依赖 Redis/DB 的可复用模块）
│   │   │   ├── routing.py           #   单次请求的选路：会话粘性、预算降级、回退链（plan_route）
│   │   │   ├── proxy.py             #   通用代理编排（故障转移 + 计费 + 日志）
│   │   │   ├── pre_checks.py        #   前置策略管线（quota / model / RPM）
│   │   │   ├── auth.py              #   JWT + API Key 认证 + RBAC 权限（ALL_PERMISSIONS、require_permission、get_current_admin）
│   │   │   ├── quota.py             #   USD 配额检查与扣减
│   │   │   ├── pricing.py           #   费用计算 + 内置模型价格表
│   │   │   ├── concurrency.py       #   Redis 并发限制
│   │   │   ├── rate_limit.py        #   Redis RPM 速率限制
│   │   │   ├── sticky_session.py    #   粘性会话（同一会话固定渠道）
│   │   │   ├── failover.py          #   故障转移判定（可重试错误识别）
│   │   │   ├── channel_health.py    #   渠道健康监测 & 自动熔断
│   │   │   ├── logging_service.py   #   请求日志持久化 + 自动清理
│   │   │   ├── metrics.py           #   Prometheus 指标
│   │   │   ├── key_pool.py          #   渠道多 Key 冷却与轮换
│   │   │   ├── spend_windows.py     #   5h/1d/7d 滚动限额
│   │   │   ├── budget_usage.py      #   Key/团队各项预算占比（降级和告警共用）
│   │   │   ├── downgrade.py         #   接近预算时改用便宜模型
│   │   │   ├── auto_cache.py        #   自动加 Anthropic cache_control
│   │   │   ├── time_pricing.py      #   分时定价倍率
│   │   │   ├── reconcile.py         #   账单 CSV 解析与比对
│   │   │   └── alerts.py            #   飞书/钉钉/企业微信/JSON 告警
│   │   ├── middleware/
│   │   │   └── request_id.py        #   注入 X-Request-ID
│   │   ├── routers/                 # API 路由（前缀 /api/*）
│   │   │   ├── openai_proxy.py      #   /v1/* OpenAI 兼容代理
│   │   │   ├── anthropic_proxy.py   #   /v1/messages Anthropic 兼容代理
│   │   │   ├── auth.py              #   /api/login、/api/me、/api/password
│   │   │   ├── channels.py          #   /api/channels CRUD + 健康管理
│   │   │   ├── keys.py              #   /api/keys CRUD
│   │   │   ├── roles.py             #   /api/roles CRUD + /api/roles/permissions
│   │   │   ├── model_groups.py      #   /api/model-groups CRUD
│   │   │   ├── models.py            #   /api/models 模型汇总视图
│   │   │   ├── logs.py              #   /api/logs 日志查询 + 清理
│   │   │   ├── model_prices.py      #   /api/model-prices CRUD + 同步内置价格
│   │   │   ├── stats.py             #   /api/stats 统计聚合
│   │   │   ├── users.py             #   /api/users 管理员 CRUD
│   │   │   ├── insights.py          #   /api/stats/cache、/api/stats/sessions
│   │   │   ├── reconcile.py         #   /api/reconcile 账单对账
│   │   │   └── metrics.py           #   Prometheus /metrics 端点
│   │   └── utils/
│   │       ├── key_generator.py     #   sk-xxx 格式 Key 生成
│   │       └── ip_check.py          #   IP 解析与白名单匹配
│   ├── migrations/                  # 数据库迁移文件
│   ├── pyproject.toml
│   ├── requirements.txt             # 唯一 Python 依赖清单（运行 + 测试）
│   ├── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router/index.ts          # 路由配置 + 权限守卫
│   │   ├── stores/auth.ts           # Pinia 认证状态（含 hasPermission）
│   │   ├── api/                     # Axios API 模块（baseURL: /api）
│   │   │   ├── client.ts            #   Axios 实例 + JWT 拦截器
│   │   │   ├── auth.ts, channels.ts, keys.ts, logs.ts
│   │   │   ├── roles.ts             #   角色 CRUD + 权限列表
│   │   │   ├── model_groups.ts      #   模型分组 CRUD
│   │   │   ├── model_prices.ts, stats.ts, users.ts
│   │   ├── layouts/AdminLayout.vue  # 侧边栏菜单（按权限显隐）
│   │   ├── styles/global.css
│   │   └── views/
│   │       ├── Login.vue, Dashboard.vue
│   │       ├── Channels.vue         #   渠道管理（含自定义定价、健康状态）
│   │       ├── ApiKeys.vue          #   Key 管理（USD 配额、模型分组）
│   │       ├── ModelGroups.vue      #   模型分组管理
│   │       ├── Roles.vue            #   角色管理（权限勾选矩阵）
│   │       ├── ModelPrices.vue, Logs.vue, Admins.vue
│   ├── vite.config.ts, tsconfig.json, package.json
│   ├── Dockerfile                   # npm build → nginx
│   └── nginx.conf
├── docker-compose.yml
├── service.sh                  # start / stop / restart / status / logs
└── .env.example
```

---

## 核心架构

### 请求处理管线

所有代理请求（`/v1/chat/completions`、`/v1/messages` 等）共享同一管线：

1. **Request ID 中间件** → 注入/复用 `X-Request-ID`
2. **API Key 认证** → SHA-256 哈希查表，检查启用/过期状态
3. **前置检查** `run_pre_checks()` → 配额检查 → 模型权限检查 → RPM 限流
4. **渠道选择** `plan_route()` 取会话、降级目标后调 `resolve_with_fallbacks()` → `resolve_candidates()` → 只保留与入口协议一致的渠道 → 按 priority 分层，层内按系统设置 `routing_strategy` 排序（`weighted` 加权随机；`least_busy` 按 Redis `five:ch_inflight:{id}` 进行中请求数；`latency` 按 `five:ch_latency:{id}` 成功请求延迟 EWMA，流式取首包时间；同分保持加权顺序）→ 粘性会话渠道提前 → 返回候选列表
5. **并发限制** `concurrency_limiter.acquire()` → Redis 原子租约（请求级 lease ID，自动续租和过期回收）
6. **代理编排** → 下面详述
7. **后置处理** `_bill_and_log()` → 计费扣费 + 写日志 + 释放并发；上游 HTTP 连接由共享连接池复用

### 按协议路由（`providers/registry.py`）

`resolve_candidates(model, preferred_protocol)` 只返回协议一致的渠道，网关不做跨协议转换：

- `/v1/messages`、`/v1/messages/count_tokens` 传入 `preferred_protocol="anthropic"`，只走 anthropic 渠道
- 其余 `/v1/*`（chat、completions、embeddings、responses、图片、语音、rerank）传入 `"openai"`，只走 openai 渠道

**渠道只有两种线协议**，`provider` 字段即协议：
- **`openai`**：OpenAI 及所有 OpenAI 兼容端点（官方、第三方中转、Gemini、Qwen 等）——统一透传
- **`anthropic`**：Anthropic 原生协议（`/v1/messages`）

候选组内按 priority + routing_strategy 排序。另一协议的渠道不参与故障转移，某协议的渠道全挂时直接报错。

> ⚠️ **`provider` 表示"线协议"，不是"厂商"。** 协议族由 `provider` 推断，Anthropic passthrough 也靠 `provider == "anthropic"` 判定。因此按**端点协议**而非厂商来建渠道：
> - 厂商的 OpenAI 兼容端点（含 Gemini / Qwen 中转）→ `provider=openai`（透传）
> - 厂商的 **Anthropic 兼容端点**（如 DeepSeek、千问）→ `provider=anthropic`，`base_url` 指向该 Anthropic 端点，`models` 填对应模型名 → 走 passthrough（保留 tool_use / thinking）
>
> 同一模型可同时建这两种渠道，`/v1/messages` 走 anthropic 渠道、`/v1/chat/completions` 走 openai 渠道。把 Anthropic 端点错填成 `provider=openai` 时，`/v1/messages` 找不到这条渠道。

### 粘性会话（`services/sticky_session.py`）

同一会话的请求尽量固定到同一渠道，提升上游 prompt 缓存命中率、避免多轮对话跨渠道串味。

- **会话标识**：优先取请求头 `X-Session-Id` / `session_id` / `X-Conversation-Id`；取不到则用请求体前缀（`system` + 首条 `user` 消息）算 SHA-256 指纹。该前缀在整段多轮对话中不变，因此无需客户端配合即可天然粘住。
- **绑定存储**：Redis `five:sticky:{api_key_id}:{session_hash} → channel_id`，TTL = `STICKY_SESSION_TTL`（默认 900s），每次成功后刷新。
- **路由注入**：路由查出 `sticky_channel_id` 传给 `resolve_candidates()`，`_promote_sticky()` 把它提到候选列表最前——**仅当该渠道仍是健康候选时**；否则保持正常排序，绑定自然回退。
- **回写时机**：`proxy.py` 的 `execute_with_failover` / `stream_with_failover` 在 `record_success()` 后调用 `bind_sticky_channel()`，故障转移到新渠道时会重新绑定。
- **关闭**：系统设置或 `STICKY_SESSION_ENABLED=false` 时 `make_session_key()` 直接返回 None。未在后台保存过时用环境变量。
- 仅对含 `messages` 的会话生效（chat/messages）；`embeddings` / 传统 `completions` 不产生指纹。

### 代理编排（`services/proxy.py`）

所有代理路由共享两个通用编排函数，协议差异通过回调注入：

- **`execute_with_failover(candidates, send_fn, ...)`** — 非流式。遍历候选渠道，调用 `send_fn(provider, channel) → (response, usage_dict)`，成功则计费返回，可重试错误则切换下一渠道。
- **`stream_with_failover(candidates, stream_fn, ...)`** — 流式。`stream_fn(provider, channel)` yield `(sse_line, usage_dict)`，流式数据开始后绑定渠道不再切换。所有 cleanup（计费、释放并发、关闭连接）在 generator 的 `finally` 中执行。

路由层只需定义 `send_fn` / `stream_fn` 闭包：

```python
# openai_proxy.py — 所有端点共享 _proxy_endpoint()
async def _send_fn(provider, channel):
    result = await provider.send_request(body_dict, endpoint)
    return result, extract_openai_usage(result)

# anthropic_proxy.py
async def _send_fn(provider, channel):
    result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
    return JSONResponse(content=result), _extract_anthropic_usage(result)
```

**请求字段与响应头**：OpenAI 路由用 `model_dump(exclude_unset=True)`，客户端没传的字段不会以 null 发给上游。Provider 把上游的 `x-ratelimit-*`、`anthropic-ratelimit-*`、`retry-after(-ms)`、`request-id` 存进 `response_headers`（`x-request-id` 改名 `x-upstream-request-id`），非流式成功和 4xx JSON 透传时带回客户端。流式由 `open_stream()` 先取第一段再发响应头，所以流式也能带上。

### 透传

| 入口 | 渠道 | 说明 |
|------|------|------|
| `/v1/messages` | provider=`anthropic` | 原样透传，tool_use、thinking、流式、厂商 Beta 字段都保留 |
| 其余 `/v1/*` | provider=`openai` | 原样透传，只按 `model_mapping` 改写模型名，流式 chat/completions 补 `stream_options.include_usage` |

客户端协议和渠道协议不一致时返回没有可用渠道。

### RBAC 权限控制（`services/auth.py`）

管理后台使用基于角色的细粒度权限控制。

**权限定义**（21 个，格式 `资源:动作`）：

| 资源 | read | write |
|------|------|-------|
| channel | 查看渠道 | 创建/编辑/删除渠道 |
| key | 查看 Key | 创建/编辑/删除 Key |
| model_group | 查看分组 | 创建/编辑/删除分组 |
| model_price | 查看定价 | 创建/编辑/删除定价 |
| log | 查看日志 | 清理日志 |
| stat | 查看统计 | — |
| user | 查看管理员 | 创建/编辑/删除管理员 |
| role | 查看角色 | 创建/编辑/删除角色 |
| security | 查看安全策略和审计摘录 | 修改关键词、密钥扫描、推理审计，并在审计页审查选中的请求 |
| setting | 查看系统设置 | 修改日志保留、粘性会话、渠道选择策略和渠道熔断参数 |
| team | 查看团队 | 创建/编辑/删除团队、重置团队用量 |

**预置角色**（内置不可删改）：

| 角色 | 权限 |
|------|------|
| Super Admin | 全部 21 个权限 |
| Viewer | 所有 `*:read` 权限（11 个） |

管理员可自建角色，自由组合权限。

**权限检查机制**：

```python
# 依赖工厂 — 声明端点所需权限
def require_permission(*required: str):
    async def checker(user = Depends(get_current_admin)):
        if not set(required).issubset(set(user.role.permissions or [])):
            raise HTTPException(403, "Permission denied")
        return user
    return Depends(checker)

# 路由使用
@router.post("/api/channels")
async def create(body: ..., user: User = require_permission("channel:write")):
    ...
```

**前端权限控制**（三层）：

| 层级 | 机制 | 示例 |
|------|------|------|
| 菜单 | `v-if="auth.hasPermission('xxx:read')"` | 无权限的页面不显示菜单 |
| 按钮 | `v-if="auth.hasPermission('xxx:write')"` | 无写权限隐藏操作按钮 |
| 路由 | `router.beforeEach` 权限守卫 | 直接输入 URL 也会重定向 |

前端仅做 UI 适配，后端是唯一安全屏障。

### 模型权限控制

`services/pre_checks.py` 中的 `get_effective_allowed_models()` 按优先级解析：

1. `api_key.model_group_id` → 查 `model_groups` 表获取模型列表
2. `api_key.allowed_models` → 直接使用
3. 两者都为空 → 允许所有模型

### 故障转移

`is_retryable_error()` 判定以下错误可重试，自动切换下一候选渠道：

| 错误类型 | 说明 |
|----------|------|
| `httpx.TimeoutException` | 上游超时 |
| `httpx.NetworkError` | 网络不可达 |
| `httpx.HTTPStatusError` (5xx) | 上游服务端错误 |
| `httpx.RemoteProtocolError` | 上游协议异常 |

4xx 错误不触发故障转移。流式请求只在尚未发送数据时才可切换。

### 号池与模型回退

- **号池**（`services/key_pool.py`）：渠道 `api_key` 存多把 Key，换行或逗号分隔。`BaseProvider.select_key()` 跳过冷却中的 Key，有会话时按会话哈希固定，否则 Redis 轮询 `five:keyrr:{channel_id}`。429 按 `retry-after(-ms)` 冷却（上限 3600 秒，缺省 30），401/403 冷却 600 秒，键为 `five:keycool:{channel_id}:{key 指纹}`。`rotate_key()` 换到下一把可用 Key 后在同一渠道重试，所有 Key 都冷却才算渠道失败。渠道测试和健康探测只用第一把。
- **模型回退**：系统设置 `model_fallbacks` `{模型: [备选, ...]}`，每条最多 5 个。`resolve_with_fallbacks()` 先排主模型的候选，再依次接上备选模型的候选，`_serving()` 给 provider 设 `model_override`，日志的 `model_actual` 记真实模型。备选模型仍受 Key 的模型权限约束。

### 成本控制

- **滚动限额**（`services/spend_windows.py`）：Key 和团队的 `window_limits` `{"5h","1d","7d": USD}`。花费按小时桶 `five:spend:{key|team}:{id}:{hour}` 累加（TTL 8 天），`begin_request_budget` 检查，`settle` 记账，重置配额时清空。
- **预算降级**（`services/downgrade.py`）：系统设置 `budget_downgrade` `{threshold, rules: {贵: 便宜}}`。压力取 `budget_usages()` 里占比最高的一项（Key 总额度、Key 窗口、团队总额度、团队窗口），达到阈值且目标模型被允许时改写模型，响应头 `x-five-downgraded-to`。
- **自动缓存**（`services/auto_cache.py`）：系统设置 `auto_cache_control` 打开后，`/v1/messages` 请求里没有任何 `cache_control` 时，在最后一个工具、系统提示、最后一条消息的最后一个非 thinking block 上加 `ephemeral` 标记。
- **分时定价**（`services/time_pricing.py`）：系统设置 `time_pricing` 规则列表 `{name, models(通配), channel_ids, start, end, utc_offset, multiplier}`，按顺序第一条命中生效，结束不晚于开始时跨午夜。`cost_breakdown()` 把各档费用和缓存节省乘以倍率，`cost_detail.time_rule` 记规则名和倍率。预留按当前时段所有命中规则的最大倍率（至少 1）放大。
- **会话**：`sticky_session.session_log_id()` 由请求头、Claude Code `metadata.user_id` 里的 `_session_<uuid>` 或对话指纹算出，写进 `request_logs.session_id`。`/api/stats/sessions` 按会话聚合。

### 告警（`services/alerts.py`）

配置存 `system_settings` 的 `alerts` 键：`enabled`、最多 10 个 webhook（`feishu` / `dingtalk` / `wecom` / `generic`，URL 和签名密钥加密，接口只返回脱敏 URL 和 `has_secret`）、`events.{budget,channel,errors}`、`budget_threshold`、`error_threshold`、`error_min_requests`。PUT 时 URL 原样回传脱敏值或留空、密钥留空都保留旧值。

| 事件 | 触发点 | 去重 |
|------|--------|------|
| 预算 | `_bill_and_log` 结算后，Key/团队的总额度或任一滚动限额占比达到阈值 | 每个预算 12 小时 |
| 渠道 | `record_failure` 计数正好等于熔断阈值；`record_success` 删掉熔断标记时 | 5 分钟 |
| 错误 | 每分钟请求数 `five:alert:req:{minute}` 达到最少请求数，且 5xx 占比达到阈值 | 10 分钟 |

去重用 `SET NX` `five:alert:{event}:{subject}`。发送在后台任务里，超时 5 秒。飞书、钉钉、企业微信返回 HTTP 200 加错误码时也算失败。告警关闭时请求路径只读一次进程缓存。

### 错误码速查

| 状态码 | code | 原因 |
|--------|------|------|
| 401 | `invalid_api_key` / `key_disabled` / `key_expired` | Key 认证失败 |
| 403 | `model_not_allowed` / `Permission denied` | Key 无权访问模型 / 管理员无权限 |
| 404 | `model_not_found` | 无启用渠道支持该模型 |
| 429 | `quota_exceeded` / `rpm_limit` / `tpm_limit` / `concurrent_limit` | 配额/每分钟请求/每分钟 token/并发超限 |
| 429 | `window_limit` / `team_window_limit` / `team_quota_exceeded` | Key 或团队的 5h/1d/7d 滚动限额、团队总额度用完 |
| 4xx | 上游 JSON | 上游 4xx 且正文是 JSON 时原样返回。配额、限流、没有渠道仍用网关自己的 `detail` |
| 502 | `upstream_error` | 上游 5xx、超时，或 4xx 正文不是 JSON |

---

## 数据模型

### roles（角色）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(64) UNIQUE | 角色名 |
| description | varchar(256) | 角色描述 |
| permissions | JSON | 权限列表 `["channel:read","key:write",...]` |
| is_builtin | bool | 内置角色不可删改 |
| created_at / updated_at | datetime | |

### admins（管理用户，模型类 `User`）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| username | varchar(64) UNIQUE | |
| hashed_password | varchar(255) | |
| role_id | int FK → roles | 关联角色 |
| is_active | bool | |
| created_at / updated_at | datetime | |

### channels（上游渠道）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) | 显示名 |
| provider | varchar(32) | 线协议：`openai`（含所有 OpenAI 兼容端点）/ `anthropic` |
| base_url | varchar(512) | 上游 API 地址 |
| api_key | text | 一把或多把上游 Key（换行分隔），整体加密存储，管理 API 返回第一把的脱敏值加 `(+N)`，列表带 `key_count` |
| models | JSON | 支持的模型列表 |
| model_mapping | JSON | 别名映射 `{"gpt-4": "gpt-4o"}` |
| model_pricing | JSON | 渠道级定价覆盖（$/1M tokens） |
| priority | int | 高优先级渠道先被选中 |
| weight | int | 同优先级按权重加权随机 |
| is_enabled | bool | |
| max_retries | int | 同渠道重试次数，默认 1 |
| timeout | int | 超时秒数 |

### api_keys

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) | 标签名 |
| key_hash | varchar(64) UNIQUE | SHA-256 哈希（明文仅创建时返回一次） |
| key_prefix | varchar(12) | 前 8 字符，用于展示 |
| quota_total | decimal(16,6) | USD 总额度，-1 = 无限 |
| quota_used | decimal(16,6) | 已消耗金额 |
| concurrent_limit | int | 最大并发数，默认 5 |
| rpm_limit | int | 每分钟最大请求数，-1 = 不限制 |
| tpm_limit | int | 每分钟最大 token 数，-1 = 不限制。请求前按估算占用，结束后按实际 prompt+completion 调整 |
| allowed_models | JSON | 模型白名单，未关联模型组时空 = 全部允许 |
| model_group_id | int FK NULL | 关联模型分组，优先于 allowed_models；空组/失效引用均拒绝全部模型 |
| allowed_ips | JSON | IP 白名单，空 = 不限制 |
| is_enabled | bool | |
| audit_policy | varchar(16) | `on` 跟随系统的关键词、密钥扫描、AI 审查和请求保存；`off` 全部跳过 |
| quota_reset_day | smallint | 每月自动重置日（1~31） |
| window_limits | JSON | 滚动限额 `{"5h": 5, "1d": 20, "7d": 80}`，USD，缺省不限 |
| team_id | int NULL | 所属团队。请求同时预留并扣减团队预算 |
| expires_at | datetime | null = 永不过期 |

### teams（团队预算）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) UNIQUE | |
| description | varchar(256) | |
| quota_total / quota_used | decimal(16,6) | USD，-1 = 不限。团队内所有 Key 共用 |
| quota_reset_day / quota_last_reset_at | | 每月重置，和 Key 共用 `reset_expired_quotas` |
| is_enabled | bool | 停用后团队内 Key 返回 403 `team_disabled` |
| window_limits | JSON | 团队滚动限额，格式同 Key |

预留键 `five:quota:team_hold:{team_id}`，和 Key 的预留一起建、一起释放。结算时 Key 和团队的 `quota_used` 都加实际费用。

### usage_daily（按天汇总）

`(day, api_key_id, model, channel_id)` 唯一，每条日志写入后 upsert 累加请求数、错误数、token 和费用，`team_id` 取最新值。`/api/stats/*` 除延迟和实时吞吐外只读这张表。延迟取窗口内最近 2 万条日志；吞吐峰值来自 Redis 每分钟计数 `five:rpm_minute:*` / `five:peak_rpm:{day}`。迁移 14 用 `request_logs` 回填历史。另累加 `cached_tokens`、`cache_write_tokens`、`cache_savings`，供成本洞察使用，迁移 17 回填前两项。

### model_groups（模型分组）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) UNIQUE | 分组名 |
| models | JSON | 模型列表 |
| created_at / updated_at | datetime | 自动管理 |

### model_prices（全局模型定价）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| model | varchar(64) UNIQUE | 模型名 |
| prompt_price | decimal(16,6) | $/1M tokens |
| completion_price | decimal(16,6) | $/1M tokens |
| cached_price | decimal(16,6) | 缓存读取价 $/1M tokens |
| cache_write_price | decimal(16,6) | 缓存写入价 $/1M tokens。Claude 内置价是输入价的 1.25 倍，其他模型与输入价相同。显式 0 表示写入免费 |
| request_price | decimal(16,6) | 按次价 USD。图片按张、语音/转写/rerank 按次，和 token 价叠加。渠道 `model_pricing` 的 `request` 键优先 |
| is_active | bool | |

### request_logs（请求日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | |
| request_id | varchar(36) | UUID |
| api_key_id / api_key_name | | 反范式 |
| channel_id / channel_name | | 反范式 |
| model_requested / model_actual | varchar(64) | mapping 前后 |
| prompt_tokens / completion_tokens / cached_tokens | int | token 计数 |
| cost | decimal(16,6) | 本次费用 USD |
| is_stream | bool | |
| failed_over | bool | 是否切换过渠道 |
| has_audit | bool | 是否另存了推理正文。列表和统计只读这个标记 |
| ai_review | varchar(32) | 事后 AI 审查结论。空表示未审查，`clear` 通过，`flagged:类别` 存疑，`unavailable` 审查失败，`skipped` 队列满了跳过 |
| security_hit | varchar(128) | 关键词名或密钥模式名，逗号分隔。命中只做标记，不改变状态码，也不写入密钥原文 |
| audit_request | text | 在 `request_log_audits`，按日志 id 一对一。只存请求，不存回复。日志详情不返回这段，`GET /api/logs/{request_id}/audit` 单独读取 |
| session_id | varchar(32) 索引 | 会话 ID，见「成本控制」 |
| cache_savings | decimal(16,6) | 相比全部按输入价计费省下的钱，扣掉缓存写入的溢价，可能为负 |
| cost_detail | JSON | `cost_breakdown()` 的明细：模型、价格来源 `channel/global/none`、各档单价、token、金额和 `time_rule`。只在日志详情返回 |
| error_origin | varchar(16) | `gateway` 网关拒绝 / `official` 官网 / `reseller` 渠道商；成功为空 |
| upstream_status_code | int | 上游 HTTP 状态，网关拒绝时为 0 |
| upstream_error | text | 上游原始报错摘录 |
| status_code / latency_ms / error_message / ip_address | | status_code 与 error_message 是返回客户端的下游结果 |

### 计费

```
cost = (fresh × prompt_price + cache_read × cached_price + cache_write × cache_write_price + completion × completion_price) / 1M
fresh = prompt - cache_read - cache_write
```

定价优先级：Channel `model_pricing` → 全局 `model_prices` 表（查价用 `model_actual`，即经 `model_mapping` 后的真实上游模型名）。渠道显式配置 `0` 是有效覆盖，不回退全局价格。渠道没填 `cache_write` 时，写入按该渠道的输入价计。扣减使用 `F()` 原子操作。

配额在请求发出前按估算费用写入 Redis 预留（`five:quota:hold:{key_id}`），响应后先把实际费用加到 `quota_used`，再释放预留。无限配额不预留，仍累计 `quota_used`。估算用当前最高输入价和输出价，不含缓存折扣。预留覆盖并发超额；价格未知时估算为 0，只挡住已经用满的额度。

内置价格表（`services/pricing.py` `DEFAULT_MODEL_PRICES`）含 80+ 个主流模型，版本由
`MODEL_PRICE_CATALOG_VERSION` 标记。管理后台“同步最新价格”会新增缺失项并刷新内置
模型价格，不修改自定义模型、启用状态或渠道级覆盖。

#### 两种协议的用量口径（重要）

费用公式按 **OpenAI 口径** 设计：`prompt_tokens` **包含** 缓存命中，`cached_tokens` 是其子集（`prompt - cached` 才是非缓存输入）。但两家上游口径不同：

| | prompt/input 是否含缓存 | 缓存字段 |
|--|--|--|
| OpenAI | **含** | `prompt_tokens_details.cached_tokens` |
| DeepSeek（OpenAI 兼容） | **含** | `prompt_cache_hit_tokens` |
| Anthropic | **不含** | `cache_read_input_tokens`（读）、`cache_creation_input_tokens`（写） |

因此凡是从 **Anthropic 上游** 取 usage 的路径，都必须把读取和写入补进 `prompt_tokens`。读取按缓存价扣，写入按 `cache_write_price` 扣。漏加写入会少计：

```
prompt_tokens = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
cached_tokens = cache_read_input_tokens
cache_write_tokens = cache_creation_input_tokens
```

归一化在 `routers/anthropic_proxy.py` 两处，改动需同步：`_extract_anthropic_usage`（非流式）和 `_passthrough_stream_with_usage`（流式）。openai 渠道本就是 OpenAI 口径，无需折算。

---

## API 参考

### 代理端点（API Key 认证）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/v1/chat/completions` | Bearer | OpenAI Chat（支持 stream） |
| POST | `/v1/completions` | Bearer | OpenAI 传统补全 |
| POST | `/v1/embeddings` | Bearer | 向量嵌入 |
| POST | `/v1/responses` | Bearer | OpenAI Responses（支持 stream，按整段 SSE 事件透传，用量取 `response.completed`） |
| POST | `/v1/images/generations` | Bearer | 图片生成，`n` 张按次计 |
| POST | `/v1/images/edits`、`/v1/images/variations` | Bearer | multipart 透传，`model` 字段按渠道映射改写 |
| POST | `/v1/audio/speech` | Bearer | 返回二进制音频。输入字符数记为 prompt_tokens，另加 1 次按次价 |
| POST | `/v1/audio/transcriptions`、`/v1/audio/translations` | Bearer | multipart 透传，1 次按次价，上游给 usage 时另计 token |
| POST | `/v1/rerank` | Bearer | token 取 `usage.prompt_tokens/total_tokens`，按次数取 `meta.billed_units.search_units`，默认 1 |
| GET | `/v1/models` | Bearer | 当前 Key 可用模型 |
| GET | `/v1/me` | Bearer | Key 配额/模型/定价信息 |
| POST | `/v1/messages` | x-api-key 或 Bearer | Anthropic Messages（支持 stream） |
| POST | `/v1/messages/count_tokens` | x-api-key 或 Bearer | 转发到 anthropic 渠道，不计费、不限流、不写日志。上游 404/405/501 时返回本地估算 |

请求示例：

```bash
# OpenAI 格式
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'

# Anthropic 格式（流式）
curl -N http://localhost:8000/v1/messages \
  -H "x-api-key: sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-sonnet-4-6", "max_tokens": 1024, "stream": true, "messages": [{"role": "user", "content": "Hello"}]}'
```

#### Claude Code 直连

```bash
export ANTHROPIC_BASE_URL=http://your-gateway:8000
export ANTHROPIC_API_KEY=sk-your-five-api-key
```

需配合 `provider: "anthropic"` 的渠道（如 Anthropic 官方、DeepSeek Anthropic 端点）以支持 tool_use。

### 管理后台 API（JWT 认证 + RBAC 权限）

所有管理接口使用 `/api/*` 前缀，通过 `require_permission("resource:action")` 控制访问权限。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/login` | — | 登录 → access_token |
| GET | `/api/me` | 登录即可 | 当前管理员信息（含角色、权限列表） |
| PUT | `/api/password` | 登录即可 | 修改密码，新密码至少 8 位，返回新 token。用 `admin123` 登录的 token 带 `pwd` 标记，`require_permission` 一律返回 403 `Password change required`，改完才放行 |
| GET/POST | `/api/channels` | channel:read / channel:write | 渠道列表/创建 |
| GET/PUT/DELETE | `/api/channels/{id}` | channel:read / channel:write | 渠道详情/更新/删除 |
| POST | `/api/channels/{id}/test` | channel:read | 测试渠道连通性 |
| POST | `/api/channels/{id}/fetch-models` | channel:read | 从上游拉取模型 |
| POST | `/api/channels/fetch-models-preview` | channel:read | 直接传参拉取模型 |
| GET | `/api/channels/health/status` | channel:read | 渠道健康状态 |
| POST | `/api/channels/{id}/recover` | channel:write | 恢复被熔断的渠道 |
| GET/POST | `/api/keys` | key:read / key:write | Key 列表/创建 |
| GET/PUT/DELETE | `/api/keys/{id}` | key:read / key:write | Key 详情/更新/删除 |
| POST | `/api/keys/{id}/reset-quota` | key:write | 重置配额 |
| GET/POST | `/api/model-groups` | model_group:read / model_group:write | 模型分组列表/创建 |
| GET | `/api/model-groups/all` | model_group:read | 全量列表（下拉框用） |
| GET/PUT/DELETE | `/api/model-groups/{id}` | model_group:read / model_group:write | 分组详情/更新/删除 |
| GET | `/api/models` | channel:read | 模型汇总（含定价和渠道来源） |
| GET/POST | `/api/model-prices` | model_price:read / model_price:write | 定价列表/创建 |
| GET/PUT/DELETE | `/api/model-prices/{id}` | model_price:read / model_price:write | 定价详情/更新/删除 |
| POST | `/api/model-prices/sync-defaults` | model_price:write | 导入内置价格 |
| GET | `/api/model-prices/unpriced` | model_price:read | 未定价模型 |
| GET/PUT | `/api/security` | security:read / security:write | 关键词标记开关，读取时一并返回密钥扫描、推理审计和 AI 审计。关键词和密钥命中只写日志标记，不中断请求 |
| GET/PUT | `/api/settings` | setting:read / setting:write | 日志保留天数、粘性会话、`routing_strategy`、渠道熔断、`model_fallbacks`、`auto_cache_control`、`budget_downgrade`、`time_pricing`。未保存过时返回环境变量默认值 |
| GET/PUT | `/api/settings/alerts` | setting:read / setting:write | 告警 webhook 和事件。URL 脱敏返回 |
| POST | `/api/settings/alerts/test` | setting:write | 给已保存的 webhook 发测试消息，`{"id": ""}` 表示全部 |
| PUT | `/api/security/inference-audit` | security:write | 推理审计总开关。只保存开启审计的 Key 的请求正文 |
| PUT | `/api/security/secret-scan` | security:write | 固定密钥模式扫描 |
| PUT | `/api/security/ai-audit` | security:write | 打开审计页使用的审查模型。不在每次请求后自动调用 |
| GET | `/api/audit/keys` | security:read | 有已保存请求的 Key |
| GET | `/api/audit/keys/{id}/requests` | security:read | 该 Key 的审查摘录。只有系统提示和最后一条用户消息 |
| POST | `/api/audit/review` | security:write | 审查选中的请求，一次最多 5 条 |
| POST/PUT/DELETE | `/api/security/keywords` | security:write | 敏感词增删改 |
| GET | `/api/logs` | log:read | 日志列表（分页+过滤，含 error_origin） |
| GET | `/api/logs/{request_id}` | log:read | 日志详情，不含请求正文 |
| GET | `/api/logs/{request_id}/audit` | log:read | 单独读取已保存的请求正文 |
| POST | `/api/logs/cleanup` | log:write | 清理过期日志 |
| GET | `/api/stats/overview` | stat:read | 总览统计 |
| GET | `/api/stats/usage` | stat:read | 时序用量 |
| GET | `/api/stats/by-model` | stat:read | 按模型统计 |
| GET | `/api/stats/by-key` | stat:read | 按 Key 统计 |
| GET | `/api/stats/by-team` | stat:read | 按团队统计 |
| GET | `/api/stats/by-channel` | stat:read | 按渠道统计 |
| GET | `/api/stats/error-rate` | stat:read | 错误率趋势 |
| GET | `/api/stats/latency` | stat:read | 延迟 P50/P95/P99 |
| GET | `/api/stats/cache` | stat:read | 缓存命中率、节省金额、趋势和按 model/key/channel 拆分 |
| GET | `/api/stats/sessions` | stat:read | 会话列表，`sort` 取 `cost`、`recent` 或 `requests` |
| GET | `/api/stats/sessions/{id}` | stat:read | 会话内的请求 |
| POST | `/api/reconcile` | stat:read | multipart 上传厂商账单 CSV，字段 `file`、`date_column`、`cost_column`、`model_column`（`-` 表示只按天）、`channel_ids`、`utc_offset`。列名留空自动识别。按天和模型对比成功请求的费用，误差 $0.01 或 5% 内算一致 |
| GET/POST | `/api/teams` | team:read / team:write | 团队列表/创建 |
| GET | `/api/teams/all` | key:read | 全量团队（Key 表单下拉用） |
| GET/PUT/DELETE | `/api/teams/{id}` | team:read / team:write | 团队详情/更新/删除（还有 Key 时 409） |
| POST | `/api/teams/{id}/reset-quota` | team:write | 团队用量清零 |
| GET/POST | `/api/users` | user:read / user:write | 管理员列表/创建 |
| PUT/DELETE | `/api/users/{id}` | user:write | 管理员更新/删除 |
| GET/POST | `/api/roles` | role:read / role:write | 角色列表/创建 |
| GET | `/api/roles/all` | 登录即可 | 全量角色列表（下拉框用） |
| GET | `/api/roles/permissions` | 登录即可 | 所有可用权限定义 |
| GET/PUT/DELETE | `/api/roles/{id}` | role:read / role:write | 角色详情/更新/删除 |
| GET | `/metrics` | `METRICS_TOKEN` 或本机 | Prometheus 指标。设了令牌凭 Bearer 访问，没设只允许 loopback。反代和 Docker 端口转发会让外部请求像私网地址，所以不按私网放行 |
| GET | `/healthz` | 无需认证 | MySQL 和 Redis 都可用返回 200，否则 503。Docker HEALTHCHECK 使用 |

分页: `?page=1&size=20`。日志过滤: `?api_key_id=&model=&status_code=&start_date=&end_date=`

---

## 配置

所有配置通过环境变量或 `.env` 管理，优先级：环境变量 > `.env` > 默认值。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | `127.0.0.1`/`3306`/`five`/`five_password`/`five_api` | |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | |
| `INIT_ADMIN_USERNAME/PASSWORD` | `admin`/`admin123` | 首次启动创建（Super Admin 角色） |
| `STICKY_SESSION_ENABLED` | `true` | 粘性会话默认开关。后台系统设置保存后以保存值为准 |
| `STICKY_SESSION_TTL` | `900` | 会话绑定默认秒数。后台保存后以保存值为准 |
| `METRICS_TOKEN` | 空 | 填了才能从容器外抓 `/metrics` |
| `LOG_RETENTION_DAYS` | `90` | 日志保留默认天数。后台保存后以保存值为准 |
| `CHANNEL_HEALTH_THRESHOLD` | `3` | 连续失败熔断默认次数。后台保存后以保存值为准 |
| `CHANNEL_HEALTH_CHECK_INTERVAL` | `60` | 熔断探测默认间隔秒数。后台保存后以保存值为准 |

Docker Compose 把数据库地址、Redis 和初始管理员写在 `docker-compose.yml` 里。改端口或密码时改这个文件，不读 `.env`。

JWT 算法固定为 HS256、有效期固定为 24 小时。令牌带 `ver`（管理员 `token_version`），改密码、管理员被改密码或停用时加 1，旧令牌返回 401 `Token revoked`。登录失败按 IP 和用户名各计数，15 分钟内 10 次返回 429。应用签名及渠道加密密钥首次启动自动
生成并持久化为 `data/.secret_key`；Docker 将项目 `data/` 挂载到容器 `/data`，
不需要配置 `SECRET_KEY`、`JWT_ALGORITHM` 或 `JWT_EXPIRE_MINUTES`。

---

## 使用流程

### 1. 创建渠道

管理后台 → Channels → Add Channel。常见配置：

渠道 `provider` 只有两个取值：`openai`（OpenAI 兼容端点）和 `anthropic`（Anthropic 原生端点）。常见上游：

| provider | 上游 | Base URL |
|----------|------|----------|
| `openai` | OpenAI 及兼容中转 | `https://api.openai.com` |
| `openai` | Google Gemini（OpenAI 兼容端点） | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `openai` | 通义千问（DashScope 兼容端点） | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `openai` | DeepSeek OpenAI 端点 | `https://api.deepseek.com` |
| `openai` | 自建 vLLM | `http://127.0.0.1:8000/v1` |
| `anthropic` | Anthropic 官方 Claude | `https://api.anthropic.com` |
| `anthropic` | DeepSeek Anthropic 端点（推荐 Claude Code） | `https://api.deepseek.com/anthropic` |

同一模型可以同时配置 OpenAI 和 Anthropic 两种协议的渠道，请求按入口协议选渠道（见按协议路由）。

> **`provider` 按端点协议填，不是按厂商填**：Anthropic 端点选 `anthropic`，供 `/v1/messages` 和 Claude Code 使用；OpenAI 端点选 `openai`，供 OpenAI SDK 等使用。
>
> vLLM 等自建 OpenAI 兼容服务直接使用 `provider=openai`。`base_url` 可填服务根地址或以 `/v1` 结尾的地址；未启用上游鉴权时 `api_key` 可留空。

#### 示例：DeepSeek 同模型双协议

DeepSeek 同时提供 OpenAI 端点（`/v1/chat/completions`）和 Anthropic 端点（`/anthropic/v1/messages`）。给同一个模型建两条渠道即可两种协议通吃：

| 渠道 | provider | base_url | models |
|------|----------|----------|--------|
| DeepSeek-OpenAI | `openai` | `https://api.deepseek.com` | `deepseek-flash`、`deepseek-v4-pro` |
| DeepSeek-Anthropic | `anthropic` | `https://api.deepseek.com/anthropic` | `deepseek-flash`、`deepseek-v4-pro` |

路由行为：
- 客户端走 `/v1/chat/completions`（OpenAI SDK） → 优先命中 **DeepSeek-OpenAI** 渠道，透传。
- 客户端走 `/v1/messages`（Claude Code / Anthropic SDK） → 优先命中 **DeepSeek-Anthropic** 渠道，passthrough，保留 tool_use / thinking。
- 某一协议的渠道全部不可用时，不会改走另一条协议。客户端要调用该模型，需要有同协议渠道。

Claude Code 直连时，配 `provider=anthropic` 的那条渠道即可：

```bash
export ANTHROPIC_BASE_URL=http://your-gateway:8000
export ANTHROPIC_API_KEY=sk-your-five-api-key
# 请求模型名用 deepseek-flash / deepseek-v4-pro
```

### 2. 创建 API Key

API Keys → Create Key：设置名称、USD 配额（-1=无限）、并发数、RPM。创建后的完整 Key 仅显示一次。

### 3. 模型分组（可选）

Model Groups → 创建分组（如 "基础模型"）→ 添加模型列表 → 在 Key 编辑中关联分组。分组优先于 Key 上的 allowed_models；空组会拒绝全部模型，已被 Key 使用的分组不能删除。

### 4. 配置定价

Model Pricing → **同步最新价格** 一键新增并刷新内置价格。也可手动添加，或在渠道编辑中设置地区价、长上下文分档等渠道级覆盖价格。

### 5. 权限管理（可选）

Roles & Permissions：创建自定义角色，勾选需要的权限。
Admins：创建管理员账号并分配角色。管理员不能禁用、删除或修改自己的角色，系统也会保留至少一个启用的 Super Admin。

### 6. 调用 API

```python
from openai import OpenAI
client = OpenAI(api_key="sk-your-key", base_url="http://your-gateway:8000/v1")
resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "Hello"}])
```

---

## 开发指南

### 分层约定

| 层 | 职责 | 示例 |
|----|------|------|
| `routers/` | 解析请求 → 调用服务 → 返回响应（薄层） | 定义 `send_fn` 闭包，调用 `execute_with_failover` |
| `services/` | 可复用业务逻辑 | `proxy.py`、`pre_checks.py`、`quota.py`、`auth.py` |
| `providers/` | 上游适配（鉴权、路径、模型名改写 + 发送） | `openai_provider.py` |
| `utils/` | 无状态工具函数 | `ip_check.py`、`key_generator.py` |

### 接入新上游

系统只有两种线协议，绝大多数上游无需写新适配器：

- **OpenAI 兼容端点**（含 Gemini/Qwen 等中转）→ 直接建 `provider=openai` 的渠道，填 base_url 即可。
- **Anthropic 兼容端点** → 建 `provider=anthropic` 的渠道。

只有当上游是一种**全新的、非 OpenAI/非 Anthropic 的原生协议**时，才需要新增适配器：

1. `app/providers/xxx_provider.py` 继承 `BaseProvider`，实现该协议的发送方法（参考 `OpenAIProvider.send_request` / `send_stream`）
2. `app/providers/registry.py` 的 `PROVIDER_MAP` 中注册，并归入 `OPENAI_PROTOCOL_PROVIDERS` 或 `ANTHROPIC_PROTOCOL_PROVIDERS`

### 添加新管理 API

1. `app/schemas/` 定义 Pydantic 模型
2. `app/routers/` 创建路由，用 `require_permission("resource:action")` 保护
3. `app/main.py` 注册 router
4. 如果引入新资源，在 `services/auth.py` 的 `ALL_PERMISSIONS` 中添加对应权限

### 添加新权限

1. `services/auth.py` 的 `ALL_PERMISSIONS` 列表中添加新权限字符串
2. 更新 `BUILTIN_ROLES` 中预置角色的权限列表
3. 路由中使用 `require_permission("new:read")` / `require_permission("new:write")`
4. 前端菜单/按钮中使用 `auth.hasPermission("new:read/write")`

### 新增前置策略

在 `services/pre_checks.py` 的 `run_pre_checks()` 中追加即可，所有代理路由自动生效。

### 代码约定

- 所有 list 接口返回 `{"total": N, "items": [...]}`
- 错误响应：OpenAI 路由用 `openai_error()`，Anthropic 路由用 `anthropic_error()`
- 认证：代理路由用 `verify_api_key`，管理路由用 `require_permission("xxx:read/write")`，仅需登录的端点用 `get_current_admin`
- 数据库变更后在 `backend/` 执行 `../.venv/bin/aerich migrate --name describe_change`，检查并提交 `migrations/`；启动前统一执行 `aerich upgrade`
- 函数职责单一，优先早返回减少嵌套
- 注释解释"为什么"而非"做了什么"

### 前端开发

- Element Plus 组件自动导入，`<script setup>` 中需编程式使用时显式 import
- API 模块在 `src/api/`，基于统一 Axios client（`baseURL: '/api'`，自动附加 JWT、401 跳转登录）
- 页面导航统一维护在 `src/config/navigation.ts`；路由、标题和菜单由该配置生成，避免三份权限映射漂移
- 路由守卫先通过 `auth.ensureProfile()` 加载权限，再按 route meta 做 fail-closed 检查；无任何可访问页面时进入 Access Denied
- 页面内写操作按钮用 `auth.hasPermission('xxx:write')` 控制显示，后端 `require_permission()` 始终是最终授权边界
- 新增管理页面：`views/Xxx.vue` → 在 `config/navigation.ts` 添加菜单项 → 在 `router/index.ts` 的 `viewComponents` 注册懒加载组件

---

## Docker Compose

| 服务 | 端口 | 说明 |
|------|------|------|
| mysql | 127.0.0.1:3306 | MySQL 8.0，只绑本机，数据在 `./data` |
| redis | 127.0.0.1:6379 | 并发限制 + RPM 限流，只绑本机 |
| gateway | 80 → 8000 | 单个镜像：前端静态文件由 FastAPI 提供，API 与 SSE 走同一进程 |

管理后台和 `/v1` 由同一个 Uvicorn 进程提供，不再单独跑 Nginx。SSE 不经过应用内缓冲。
IP 白名单读取 `request.client`；部署反向代理时只能通过 Uvicorn
`--forwarded-allow-ips` 信任明确的代理网段，不能在应用层直接相信任意
`X-Forwarded-For`。镜像沿用 Uvicorn 默认：只信任 `127.0.0.1`，需要时设环境变量 `FORWARDED_ALLOW_IPS`。

---

## 常见问题

**首次启动没有管理员？** 检查 `.env` 中 `INIT_ADMIN_USERNAME/PASSWORD`，应用启动时 admins 表为空则自动创建（Super Admin 角色）。同时自动创建预置角色（Super Admin、Viewer）。用默认密码登录后会被引导到 `/password` 改密码。

**流式响应不工作？** 默认部署由网关进程直接输出 SSE。如果前面又加了 Nginx 或其他反代，需要关闭响应缓冲（Nginx 的 `proxy_buffering off`）。

**Token 计费不准确？** 非流式直接用上游 `usage`；流式从 SSE 事件中提取。流式结束时仍没有 usage（客户端中途断开或上游不返回），输出按已转发的文本估算（中日韩字符 1 token，其余 4 字符 1 token，含 reasoning 和工具参数），输入取预留时的估算值。非流式上游未返回 usage 时记 0。定价查找：Channel `model_pricing` → 全局 `model_prices` 表。注意 Anthropic 的 `input_tokens` 不含缓存，取用时须补齐为 `input + cache_read + cache_creation`（详见「两种协议的用量口径」）。

**渠道测试失败？** `provider=openai` 测试 `GET /v1/models`，`provider=anthropic` 测试发送最小请求到 `/v1/messages`。检查 Base URL 和 API Key。

**日志追踪？** 从响应头获取 `X-Request-ID` → 管理后台 Logs 页面搜索。

**权限不够？** 403 Permission denied — 当前管理员的角色缺少所需权限。联系 Super Admin 调整角色权限或分配其他角色。

**同一模型两个渠道如何路由？** `/v1/messages` 只走 Anthropic 渠道，`/v1/chat/completions` 只走 OpenAI 兼容渠道。另一协议的渠道不会被选中。
