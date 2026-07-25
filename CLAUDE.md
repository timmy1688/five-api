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
cp .env.example .env && vi .env    # 修改数据库和初始管理员密码
docker compose up -d
docker compose logs -f backend     # 查看日志
```

启动后：前端 `http://localhost:80`、后端 API `http://localhost:8000`、默认管理员 `admin` / `admin123`（Super Admin 角色）

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
cp .env.example .env
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
│   │   │   ├── anthropic_provider.py#   Anthropic 协议（原生直通 + 格式转换）
│   │   │   └── registry.py          #   渠道选择 & 模型路由（含协议优先）
│   │   ├── services/                # 基础设施（依赖 Redis/DB 的可复用模块）
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
│   │   │   └── anthropic_compat.py  #   Anthropic↔OpenAI 格式转换（含工具/tool_use，方向 A）
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
4. **渠道选择** `resolve_candidates()` → 协议优先（匹配协议的渠道排前面）→ 按 priority 分层 + weight 加权随机 → 粘性会话渠道提前 → 返回候选列表
5. **并发限制** `concurrency_limiter.acquire()` → Redis 原子租约（请求级 lease ID，自动续租和过期回收）
6. **代理编排** → 下面详述
7. **后置处理** `_bill_and_log()` → 计费扣费 + 写日志 + 释放并发；上游 HTTP 连接由共享连接池复用

### 协议优先路由（`providers/registry.py`）

`resolve_candidates(model, preferred_protocol)` 支持协议优先排序：

- `/v1/messages` 路由传入 `preferred_protocol="anthropic"` → anthropic 渠道优先（passthrough）
- `/v1/chat/completions` 路由传入 `preferred_protocol="openai"` → openai 渠道优先
- `/v1/completions`、`/v1/embeddings` 不做跨协议转换，只允许 `openai` 渠道

**渠道只有两种线协议**，`provider` 字段即协议：
- **`openai`**：OpenAI 及所有 OpenAI 兼容端点（官方、第三方中转、Gemini、Qwen 等）——统一透传
- **`anthropic`**：Anthropic 原生协议（`/v1/messages`）

匹配协议的渠道整体排在不匹配的前面，各组内维持 priority + weight 排序。不匹配的渠道保留作为故障转移备选。

> ⚠️ **`provider` 表示"线协议"，不是"厂商"。** 协议族由 `provider` 推断，Anthropic passthrough 也靠 `provider == "anthropic"` 判定。因此按**端点协议**而非厂商来建渠道：
> - 厂商的 OpenAI 兼容端点（含 Gemini / Qwen 中转）→ `provider=openai`（透传）
> - 厂商的 **Anthropic 兼容端点**（如 DeepSeek、千问）→ `provider=anthropic`，`base_url` 指向该 Anthropic 端点，`models` 填对应模型名 → 走 passthrough（保留 tool_use / thinking）
>
> 同一模型可同时建这两种渠道，`/v1/messages` 自动优先走 anthropic 渠道、`/v1/chat/completions` 优先走 openai 渠道。**切勿**把 Anthropic 端点错填成 `provider=openai`，否则会走转换路径（丢失 tool_use）。

### 粘性会话（`services/sticky_session.py`）

同一会话的请求尽量固定到同一渠道，提升上游 prompt 缓存命中率、避免多轮对话跨渠道串味。

- **会话标识**：优先取请求头 `X-Session-Id` / `session_id` / `X-Conversation-Id`；取不到则用请求体前缀（`system` + 首条 `user` 消息）算 SHA-256 指纹。该前缀在整段多轮对话中不变，因此无需客户端配合即可天然粘住。
- **绑定存储**：Redis `five:sticky:{api_key_id}:{session_hash} → channel_id`，TTL = `STICKY_SESSION_TTL`（默认 900s），每次成功后刷新。
- **路由注入**：路由查出 `sticky_channel_id` 传给 `resolve_candidates()`，`_promote_sticky()` 把它提到候选列表最前——**仅当该渠道仍是健康候选时**；否则保持正常排序，绑定自然回退。
- **协议优先高于跨协议粘性**：若粘性渠道属于 **非** preferred 协议组、而 preferred 协议组仍有健康渠道，则 `_promote_sticky()` **忽略粘性**、回到协议优先排序。这避免了「preferred 协议渠道临时故障 → fallback 到跨协议渠道 → 恢复后仍被粘性长期卡住」的问题。粘性渠道属于 preferred 组、或 preferred 组无健康渠道（真需 fallback）时才提升。
- **回写时机**：`proxy.py` 的 `execute_with_failover` / `stream_with_failover` 在 `record_success()` 后调用 `bind_sticky_channel()`，故障转移到新渠道时会重新绑定。结合上一条：preferred 渠道恢复后，下一次请求即按协议优先走回该渠道并把粘性重绑过去，实现自愈——无需手动清 Redis 或等 TTL 过期。
- **关闭**：`STICKY_SESSION_ENABLED=false` 时 `make_session_key()` 直接返回 None，管线零开销。
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

# anthropic_proxy.py — passthrough 分支
async def _send_fn(provider, channel):
    if is_passthrough:
        result = await provider.send_anthropic_passthrough(raw_body, extra_headers)
        return JSONResponse(content=result), _extract_anthropic_usage(result)
    else:  # conversion path
        ...
```

### Anthropic 代理的两条路径

| 条件 | 路径 | 说明 |
|------|------|------|
| `/v1/messages` + provider=`anthropic` | **Passthrough** | 原样透传，支持 tool_use/thinking/streaming 全部特性 |
| `/v1/messages` + provider=`openai` | **Conversion（方向 A）** | `anthropic_compat.py`：Anthropic→OpenAI 请求、OpenAI→Anthropic 响应/流 |
| `/v1/chat/completions` + provider=`anthropic` | **Conversion（方向 B）** | `anthropic_provider.py`：OpenAI→Anthropic 请求、Anthropic→OpenAI 响应/流 |

### 跨协议工具转换（tool-aware conversion）

两条 Conversion 路径都支持 **工具调用（function calling）** 的全链路双向转换，不再局限于纯文本：

| 概念 | Anthropic 侧 | OpenAI 侧 |
|------|-------------|-----------|
| 工具定义 | `tools[].input_schema` | `tools[].function.parameters` |
| 工具选择 | `tool_choice: {auto/any/tool/none}` | `tool_choice: auto/required/none/{function}` |
| 模型发起调用 | content block `tool_use` | `message.tool_calls` |
| 回传工具结果 | user 消息里的 `tool_result` block | 独立的 `role:"tool"` 消息 |
| 结束原因 | `stop_reason: tool_use` | `finish_reason: tool_calls` |

要点：
- **多轮往返**：历史消息里的 `tool_use` / `tool_result` 会被正确互转，多轮工具对话不断链。连续的 OpenAI `tool` 消息合并进一个 Anthropic user 消息的多个 `tool_result` block（满足角色交替约束）。
- **流式**：方向 A 的工具参数按 index 累积、在流末统一以 `input_json_delta` 输出（规避并行工具调用分片交错乱序）；方向 B 用「Anthropic block index → OpenAI tool_call index」映射把 `input_json_delta` 转成 `delta.tool_calls` 分片。
- **局限**：Conversion 路径的图片等多模态 block 按最佳努力降级为文本；追求全特性时应让客户端协议与渠道 `provider` 一致，走 Passthrough。

### RBAC 权限控制（`services/auth.py`）

管理后台使用基于角色的细粒度权限控制。

**权限定义**（15 个，格式 `资源:动作`）：

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

**预置角色**（内置不可删改）：

| 角色 | 权限 |
|------|------|
| Super Admin | 全部 15 个权限 |
| Viewer | 所有 `*:read` 权限（8 个） |

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

### 错误码速查

| 状态码 | code | 原因 |
|--------|------|------|
| 401 | `invalid_api_key` / `key_disabled` / `key_expired` | Key 认证失败 |
| 403 | `model_not_allowed` / `Permission denied` | Key 无权访问模型 / 管理员无权限 |
| 404 | `model_not_found` | 无启用渠道支持该模型 |
| 429 | `quota_exceeded` / `rpm_limit` / `concurrent_limit` | 配额/速率/并发超限 |
| 502 | `upstream_error` | 所有候选渠道均失败 |

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
| api_key | varchar(512) | 使用首次启动自动生成的持久密钥加密存储，管理 API 仅返回脱敏值 |
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
| allowed_models | JSON | 模型白名单，未关联模型组时空 = 全部允许 |
| model_group_id | int FK NULL | 关联模型分组，优先于 allowed_models；空组/失效引用均拒绝全部模型 |
| allowed_ips | JSON | IP 白名单，空 = 不限制 |
| is_enabled | bool | |
| quota_reset_day | smallint | 每月自动重置日（1~31） |
| expires_at | datetime | null = 永不过期 |

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
| cached_price | decimal(16,6) | 缓存命中价 $/1M tokens |
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
| status_code / latency_ms / error_message / ip_address | | |

### 计费

```
cost = ((prompt - cached) × prompt_price + cached × cached_price + completion × completion_price) / 1M
```

定价优先级：Channel `model_pricing` → 全局 `model_prices` 表（查价用 `model_actual`，即经 `model_mapping` 后的真实上游模型名）。渠道显式配置 `0` 是有效覆盖，不回退全局价格。扣减使用 `F()` 原子操作。

配额按上游响应中的实际用量后扣，是软上限。检查和扣费本身并发安全，但多个请求在达到上限前已同时放行时，最终用量允许小幅超额；若要严格硬上限，需要引入请求前额度预留与响应后结算机制，当前精简实现不做额度账本。

内置价格表（`services/pricing.py` `DEFAULT_MODEL_PRICES`）含 80+ 个主流模型，版本由
`MODEL_PRICE_CATALOG_VERSION` 标记。管理后台“同步最新价格”会新增缺失项并刷新内置
模型价格，不修改自定义模型、启用状态或渠道级覆盖。

#### 跨协议计费口径统一（重要）

费用公式按 **OpenAI 口径** 设计：`prompt_tokens` **包含** 缓存命中，`cached_tokens` 是其子集（`prompt - cached` 才是非缓存输入）。但两家上游口径不同：

| | prompt/input 是否含缓存 | 缓存字段 |
|--|--|--|
| OpenAI | **含** | `prompt_tokens_details.cached_tokens` |
| DeepSeek（OpenAI 兼容） | **含** | `prompt_cache_hit_tokens` |
| Anthropic | **不含** | `cache_read_input_tokens`（读）、`cache_creation_input_tokens`（写） |

因此凡是从 **Anthropic 上游** 取 usage 的路径，都必须折算成 OpenAI 口径，否则 `prompt - cached` 会把非缓存 token 也减掉导致**少计费**：

```
prompt_tokens = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
cached_tokens = cache_read_input_tokens          # cache_creation 暂按 prompt_price 计（无专门 cache-write 价）
```

归一化位置共 4 处（改动需同步维护）：
- `routers/anthropic_proxy.py` `_extract_anthropic_usage`（passthrough 非流式）
- `routers/anthropic_proxy.py` `_passthrough_stream_with_usage`（passthrough 流式）
- `providers/anthropic_provider.py` `transform_response`（方向 B 非流式）
- `providers/anthropic_provider.py` `stream_transform`（方向 B 流式）

方向 A（openai 上游）本就是 OpenAI 口径，无需折算。归一化后所有路径共用同一公式，同一请求无论走 passthrough / 方向 A / 方向 B，`prompt_tokens` 与 cost 完全一致。

> ⚠️ **流式转换必须请求 usage**：Anthropic→openai 渠道（方向 A）转换时，`anthropic_to_openai_request` 会在流式下自动附加 `stream_options={"include_usage": true}`，否则 OpenAI 兼容上游流式默认不返回 usage，会导致 token 记 0。

---

## API 参考

### 代理端点（API Key 认证）

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/v1/chat/completions` | Bearer | OpenAI Chat（支持 stream） |
| POST | `/v1/completions` | Bearer | OpenAI 传统补全 |
| POST | `/v1/embeddings` | Bearer | 向量嵌入 |
| GET | `/v1/models` | Bearer | 当前 Key 可用模型 |
| GET | `/v1/me` | Bearer | Key 配额/模型/定价信息 |
| POST | `/v1/messages` | x-api-key 或 Bearer | Anthropic Messages（支持 stream） |

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
| PUT | `/api/password` | 登录即可 | 修改密码 |
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
| GET | `/api/logs` | log:read | 日志列表（分页+过滤） |
| POST | `/api/logs/cleanup` | log:write | 清理过期日志 |
| GET | `/api/stats/overview` | stat:read | 总览统计 |
| GET | `/api/stats/usage` | stat:read | 时序用量 |
| GET | `/api/stats/by-model` | stat:read | 按模型统计 |
| GET | `/api/stats/by-key` | stat:read | 按 Key 统计 |
| GET | `/api/stats/by-channel` | stat:read | 按渠道统计 |
| GET | `/api/stats/error-rate` | stat:read | 错误率趋势 |
| GET | `/api/stats/latency` | stat:read | 延迟 P50/P95/P99 |
| GET/POST | `/api/users` | user:read / user:write | 管理员列表/创建 |
| PUT/DELETE | `/api/users/{id}` | user:write | 管理员更新/删除 |
| GET/POST | `/api/roles` | role:read / role:write | 角色列表/创建 |
| GET | `/api/roles/all` | 登录即可 | 全量角色列表（下拉框用） |
| GET | `/api/roles/permissions` | 登录即可 | 所有可用权限定义 |
| GET/PUT/DELETE | `/api/roles/{id}` | role:read / role:write | 角色详情/更新/删除 |
| GET | `/metrics` | 无需认证 | Prometheus 指标 |

分页: `?page=1&size=20`。日志过滤: `?api_key_id=&model=&status_code=&start_date=&end_date=`

---

## 配置

所有配置通过环境变量或 `.env` 管理，优先级：环境变量 > `.env` > 默认值。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | `127.0.0.1`/`3306`/`five`/`five_password`/`five_api` | |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | |
| `INIT_ADMIN_USERNAME/PASSWORD` | `admin`/`admin123` | 首次启动创建（Super Admin 角色） |
| `STICKY_SESSION_ENABLED` | `true` | 粘性会话开关 |
| `STICKY_SESSION_TTL` | `900` | 会话→渠道绑定的 Redis 过期秒数 |

Docker Compose 额外: `MYSQL_ROOT_PASSWORD`、`BACKEND_PORT`(8000)、`FRONTEND_PORT`(80)、`REDIS_PORT`(6379)

JWT 算法固定为 HS256、有效期固定为 24 小时。应用签名及渠道加密密钥首次启动自动
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

同一模型可以同时配置 OpenAI 和 Anthropic 两种协议的渠道，系统会根据请求来源协议自动优先匹配（见协议优先路由）。

> **`provider` 按端点协议填，不是按厂商填**：Anthropic 端点选 `anthropic` 可保留供应商 Beta 字段；OpenAI 端点选 `openai`，工具调用会在两种协议间自动转换。
>
> vLLM 等自建 OpenAI 兼容服务直接使用 `provider=openai`。`base_url` 可填服务根地址或以 `/v1` 结尾的地址；未启用上游鉴权时 `api_key` 可留空。

#### 示例：DeepSeek 同模型双协议

DeepSeek 同时提供 OpenAI 端点（`/v1/chat/completions`）和 Anthropic 端点（`/anthropic/v1/messages`）。给同一个模型建两条渠道即可两种协议通吃：

| 渠道 | provider | base_url | models |
|------|----------|----------|--------|
| DeepSeek-OpenAI | `openai` | `https://api.deepseek.com` | `deepseek-v4-flash`、`deepseek-v4-pro` |
| DeepSeek-Anthropic | `anthropic` | `https://api.deepseek.com/anthropic` | `deepseek-v4-flash`、`deepseek-v4-pro` |

路由行为：
- 客户端走 `/v1/chat/completions`（OpenAI SDK） → 优先命中 **DeepSeek-OpenAI** 渠道，透传。
- 客户端走 `/v1/messages`（Claude Code / Anthropic SDK） → 优先命中 **DeepSeek-Anthropic** 渠道，passthrough，保留 tool_use / thinking。
- 若首选协议的渠道全部故障，另一条渠道作为故障转移备选（跨协议时自动走转换路径）。

Claude Code 直连时，配 `provider=anthropic` 的那条渠道即可：

```bash
export ANTHROPIC_BASE_URL=http://your-gateway:8000
export ANTHROPIC_API_KEY=sk-your-five-api-key
# 请求模型名用 deepseek-v4-flash / deepseek-v4-pro
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
| `providers/` | 上游适配（请求转换 + 发送） | `openai_provider.py` |
| `utils/` | 无状态工具函数 | `ip_check.py`、`key_generator.py` |

### 接入新上游

系统只有两种线协议，绝大多数上游无需写新适配器：

- **OpenAI 兼容端点**（含 Gemini/Qwen 等中转）→ 直接建 `provider=openai` 的渠道，填 base_url 即可。
- **Anthropic 兼容端点** → 建 `provider=anthropic` 的渠道。

只有当上游是一种**全新的、非 OpenAI/非 Anthropic 的原生协议**时，才需要新增适配器：

1. `app/providers/xxx_provider.py` 继承 `BaseProvider`，实现 `transform_request`、`transform_response`、`stream_transform`
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
| mysql | 3306 | MySQL 8.0，数据持久化到 named volume |
| redis | 6379 | 并发限制 + RPM 限流 |
| backend | 8000 | FastAPI，等待 mysql/redis healthy |
| frontend | 80 | npm build → Nginx（SPA + 反代 + SSE 支持） |

Nginx 要点：`/v1/` 反代关闭 `proxy_buffering` 以支持 SSE，300s 超时。
IP 白名单读取 `request.client`；部署反向代理时只能通过 Uvicorn
`--forwarded-allow-ips` 信任明确的代理网段，不能在应用层直接相信任意
`X-Forwarded-For`。Docker 镜像默认仅信任 loopback 与 Docker 私网段。

---

## 常见问题

**首次启动没有管理员？** 检查 `.env` 中 `INIT_ADMIN_USERNAME/PASSWORD`，应用启动时 admins 表为空则自动创建（Super Admin 角色）。同时自动创建预置角色（Super Admin、Viewer）。

**流式响应不工作？** 确认 Nginx 配置了 `proxy_buffering off`，所有中间反代层都关闭了 response buffering。

**Token 计费不准确？** 非流式直接用上游 `usage`；流式从 SSE 事件中提取。上游未返回 usage 时 tokens 记为 0、cost 为 $0。定价查找：Channel `model_pricing` → 全局 `model_prices` 表。注意跨协议口径统一：Anthropic 的 `input_tokens` 不含缓存，取用时须补齐为 `input + cache_read + cache_creation`（详见「跨协议计费口径统一」）。流式走 Anthropic→openai 转换时依赖 `stream_options.include_usage`，否则上游不吐 usage 会记 0。

**渠道测试失败？** `provider=openai` 测试 `GET /v1/models`，`provider=anthropic` 测试发送最小请求到 `/v1/messages`。检查 Base URL 和 API Key。

**日志追踪？** 从响应头获取 `X-Request-ID` → 管理后台 Logs 页面搜索。

**权限不够？** 403 Permission denied — 当前管理员的角色缺少所需权限。联系 Super Admin 调整角色权限或分配其他角色。

**同一模型两个渠道如何路由？** 系统根据请求协议自动优先匹配：`/v1/messages` 优先走 Anthropic 渠道，`/v1/chat/completions` 优先走 OpenAI 兼容渠道。不匹配的渠道作为故障转移备选。
