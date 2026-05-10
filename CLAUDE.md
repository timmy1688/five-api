# CLAUDE.md — Five API Gateway 开发指南

## 项目简介

Five API 是一个自托管的 AI API 网关，对外暴露 OpenAI 兼容接口和 Anthropic 兼容接口，内部将请求路由到多个上游 LLM 提供商（OpenAI、Anthropic Claude、Google Gemini、Alibaba Qwen）。附带 Vue 3 管理后台用于渠道管理、API Key 管理、用量统计和日志查看。支持 Claude Code 直连。

**技术栈**: FastAPI + Tortoise ORM + MySQL + Redis（后端）| Vue 3 + Element Plus + ECharts（前端）| Docker Compose（部署）

---

## 快速开始

### 环境要求

- Python >= 3.11
- Node.js >= 20
- MySQL 8.0
- Redis 7+
- 或直接使用 Docker Compose

### 方式一：Docker Compose 一键部署

```bash
cd /opt/five-api

# 复制并编辑环境变量（修改密码和密钥）
cp .env.example .env
vi .env

# 启动所有服务（MySQL + Redis + 后端 + 前端）
docker compose up -d

# 查看日志
docker compose logs -f backend
```

启动后：
- 前端管理后台：`http://localhost:80`（可通过 `FRONTEND_PORT` 修改）
- 后端 API：`http://localhost:8000`（可通过 `BACKEND_PORT` 修改）
- 默认管理员：`admin` / `admin123`（通过 `.env` 中 `INIT_ADMIN_USERNAME` 和 `INIT_ADMIN_PASSWORD` 配置）

### 方式二：本地开发

```bash
# 方法 A：使用 start.sh 一键启动
./start.sh
# 前端: http://localhost:5001  后端: http://localhost:5002
# 停止: ./stop.sh

# 方法 B：手动启动
# 1. 启动 MySQL + Redis
docker compose up -d mysql redis

# 2. 后端
cd /opt/five-api/backend
cp .env.example .env          # 编辑数据库连接等配置
pip install -e ".[dev]"       # 安装依赖
uvicorn app.main:app --reload --port 5002

# 3. 前端（新终端）
cd /opt/five-api/frontend
npm install
npx vite --port 5001          # 启动开发服务器
```

前端 Vite dev server 已配置代理，`/api` 和 `/v1` 请求自动转发到 `http://127.0.0.1:5002`。

---

## 项目结构

```
/opt/five-api/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI 应用入口，lifespan，中间件注册
│   │   ├── config.py                # pydantic-settings 配置 + Tortoise ORM 配置
│   │   ├── dependencies.py          # Redis 连接管理
│   │   ├── models/                  # Tortoise ORM 数据模型
│   │   │   ├── admin.py             #   管理员
│   │   │   ├── channel.py           #   上游渠道（含 model_pricing）
│   │   │   ├── api_key.py           #   API Key（SHA-256 哈希，USD 配额）
│   │   │   ├── model_price.py       #   全局模型定价（含 cached_price）
│   │   │   └── request_log.py       #   请求日志（含 cost、cached_tokens）
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   │   ├── openai.py            #   OpenAI 兼容格式
│   │   │   ├── anthropic.py         #   Anthropic 兼容格式
│   │   │   ├── admin.py             #   管理员相关
│   │   │   ├── channel.py           #   渠道 CRUD（含 model_pricing）
│   │   │   ├── api_key.py           #   Key CRUD（USD 配额）
│   │   │   ├── model_price.py       #   模型定价 CRUD（含 cached_price）
│   │   │   └── stats.py             #   统计数据（含 cost）
│   │   ├── providers/               # 上游提供商适配器（核心）
│   │   │   ├── base.py              #   抽象基类 BaseProvider
│   │   │   ├── openai_provider.py   #   OpenAI（透传）
│   │   │   ├── anthropic_provider.py#   Anthropic Claude（完整转换 + 原生直通，含缓存 token 映射）
│   │   │   ├── gemini_provider.py   #   Google Gemini（透传）
│   │   │   ├── qwen_provider.py     #   Alibaba Qwen（透传）
│   │   │   └── registry.py          #   渠道选择 & 模型路由
│   │   ├── services/                # 业务逻辑层
│   │   │   ├── auth.py              #   JWT + API Key 认证
│   │   │   ├── quota.py             #   USD 配额检查与扣减
│   │   │   ├── pricing.py           #   费用计算 + 内置主流模型价格表
│   │   │   ├── concurrency.py       #   Redis Lua 脚本并发限制
│   │   │   ├── logging_service.py   #   请求日志持久化
│   │   │   ├── anthropic_compat.py  #   Anthropic↔OpenAI 格式转换
│   │   │   └── proxy.py             #   流式代理编排
│   │   ├── middleware/
│   │   │   └── request_id.py        #   ASGI 中间件，注入 X-Request-ID
│   │   ├── routers/                 # API 路由
│   │   │   ├── openai_proxy.py      #   /v1/* OpenAI 兼容代理路由
│   │   │   ├── anthropic_proxy.py   #   /v1/messages Anthropic 兼容代理路由
│   │   │   ├── admin_auth.py        #   管理员登录
│   │   │   ├── admin_channels.py    #   渠道 CRUD
│   │   │   ├── admin_keys.py        #   Key CRUD
│   │   │   ├── admin_logs.py        #   日志查询
│   │   │   ├── admin_model_prices.py#   模型定价 CRUD + 同步内置价格 + 未定价模型查询
│   │   │   └── admin_stats.py       #   统计聚合
│   │   └── utils/
│   │       └── key_generator.py     #   sk-xxx 格式 Key 生成
│   ├── migrations/                  # Aerich 迁移文件
│   ├── pyproject.toml               # Python 依赖配置
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── main.ts                  # Vue 应用入口
│   │   ├── App.vue                  # 根组件
│   │   ├── router/index.ts          # 路由配置 + 导航守卫
│   │   ├── stores/auth.ts           # Pinia 认证状态
│   │   ├── api/                     # Axios API 模块
│   │   │   ├── client.ts            #   Axios 实例 + 拦截器
│   │   │   ├── auth.ts              #   登录/个人信息
│   │   │   ├── channels.ts          #   渠道 CRUD
│   │   │   ├── keys.ts              #   Key CRUD
│   │   │   ├── logs.ts              #   日志查询
│   │   │   ├── model_prices.ts      #   模型定价 CRUD + 同步 + 未定价查询
│   │   │   └── stats.ts             #   统计数据
│   │   ├── layouts/AdminLayout.vue  # 管理后台布局（侧边栏+顶栏）
│   │   ├── styles/global.css        # 全局样式（表格对齐等）
│   │   └── views/                   # 页面组件
│   │       ├── Login.vue            #   登录页
│   │       ├── Dashboard.vue        #   统计仪表盘（Cost + Tokens）
│   │       ├── Channels.vue         #   渠道管理（含自定义定价 prompt/completion/cached）
│   │       ├── ApiKeys.vue          #   Key 管理（USD 配额）
│   │       ├── ModelPrices.vue      #   模型定价管理（含缓存价格、同步内置、未定价提示）
│   │       └── Logs.vue             #   请求日志（Input/Output/Cache 分列显示）
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── Dockerfile                   # 多阶段构建：npm build → nginx
│   └── nginx.conf                   # Nginx 反代 + SSE 支持
├── docker-compose.yml               # 完整部署：mysql + redis + backend + frontend
├── .env.example                     # Docker Compose 环境变量模板
├── start.sh                         # 本地开发一键启动（MySQL/Redis + 后端 + 前端）
├── stop.sh                          # 本地开发一键停止
└── .gitignore
```

---

## 核心架构

### 请求处理全链路

网关有两个入口端点：`POST /v1/chat/completions`（OpenAI 格式）和 `POST /v1/messages`（Anthropic 格式）。以下以 `/v1/chat/completions` 为主线，标注 `/v1/messages` 的差异：

#### 第 1 步：Request ID 中间件

**文件**: `middleware/request_id.py`

```
请求进入 Nginx → 转发到 FastAPI
  │
  ├─ 检查请求头 X-Request-ID
  │   ├─ 有: 复用客户端传入的 ID
  │   └─ 无: 生成 uuid4
  │
  ├─ 写入 scope["state"]["request_id"]（后续步骤可读取）
  └─ 响应头自动附上 X-Request-ID（用于链路追踪）
```

#### 第 2 步：API Key 认证

**文件**: `services/auth.py` → `verify_api_key()` / `verify_api_key_anthropic()`

```
/v1/chat/completions: 提取 Authorization: Bearer sk-abc123...
/v1/messages:         提取 x-api-key: sk-abc123...（也支持 Authorization: Bearer）
  │
  ├─ sha256("sk-abc123...") → key_hash
  ├─ SELECT * FROM api_keys WHERE key_hash = ?
  │
  ├─ 找不到     → 401 invalid_api_key "Invalid API key"
  ├─ is_enabled=False → 401 key_disabled "API key is disabled"
  ├─ expires_at < now → 401 key_expired "API key has expired"
  └─ 通过 → 返回 APIKey 对象（后续步骤使用）
```

#### 第 3 步：配额前置检查

**文件**: `services/quota.py` → `check_quota()`

```
check_quota(api_key):
  ├─ quota_total == -1     → 通过（无限额度）
  ├─ quota_used < quota_total → 通过
  └─ quota_used >= quota_total → 429 quota_exceeded "Spending quota exceeded"
```

> **注意**: 这是前置粗检查，非原子扣减。扣减在请求完成后执行（第 7 步）。并发请求可能都通过检查后各自扣减，导致微小超额（一两次请求的费用），这是可接受的。

#### 第 4 步：模型权限检查

**文件**: `routers/openai_proxy.py` → `_check_model_access()`

```
_check_model_access(api_key, "gpt-4o"):
  ├─ allowed_models 为空列表 → 允许所有模型，通过
  ├─ "gpt-4o" in allowed_models → 通过
  └─ "gpt-4o" not in allowed_models → 403 model_not_allowed
```

#### 第 5 步：渠道选择 + Provider 实例化

**文件**: `providers/registry.py` → `resolve_channel()`

```
resolve_channel("gpt-4o"):
  │
  ├─ SELECT * FROM channels WHERE is_enabled=True
  ├─ 过滤: "gpt-4o" in channel.models
  │   └─ 无候选渠道 → 404 model_not_found
  │
  ├─ 按 priority 降序排列
  ├─ 取最高优先级组（如所有 priority=10 的渠道）
  ├─ 按 weight 加权随机选一个
  │   例: 渠道A(weight=3) 渠道B(weight=1) → A 有 75% 概率被选中
  │
  ├─ 查 PROVIDER_MAP[channel.provider]
  │   "openai"    → OpenAIProvider（透传）
  │   "anthropic" → AnthropicProvider（/v1/messages 直通 或 /v1/chat/completions 格式转换）
  │   "gemini"    → GeminiProvider（透传）
  │   "qwen"      → QwenProvider（透传）
  │   未知        → 500 unsupported_provider
  │
  └─ 返回 (channel, provider_instance)
      provider 内部创建 httpx.AsyncClient(base_url=channel.base_url)
```

#### 第 6 步：并发限制

**文件**: `services/concurrency.py` → Redis Lua 脚本

```
concurrency_limiter.acquire(api_key.id, concurrent_limit):
  │
  ├─ Redis Lua 原子操作:
  │   INCR five:concurrency:{key_id}
  │   首次 INCR → EXPIRE 120s（防崩溃后永不过期）
  │   current > limit → DECR 回退，返回 0（拒绝）
  │
  ├─ 返回 1 → 获取成功，继续
  └─ 返回 0 → 关闭 provider → 429 concurrent_limit "Too many concurrent requests"
```

> **安全机制**: Redis key 设置 120 秒 TTL。即使代码崩溃未释放，120 秒后 key 自动过期，并发计数归零。

#### 第 7 步：发送请求到上游（分三条路径）

##### 路径 A：OpenAI 格式（`/v1/chat/completions`）

**文件**: `routers/openai_proxy.py`，`services/proxy.py`

无论上游 provider 类型是什么，请求体经过 provider 的 `transform_request()` 转为上游格式，响应经过 `transform_response()` 转回 OpenAI 格式。

```
非流式: provider.send_request() → transform → httpx POST → transform_response → JSON
流式:   StreamingResponse(stream_proxy()) → send_stream → stream_transform → SSE
```

##### 路径 B：Anthropic 直通（`/v1/messages` + `provider=anthropic`）

**文件**: `routers/anthropic_proxy.py` → `_handle_anthropic_passthrough()`

当请求通过 `/v1/messages` 进入且渠道 provider 为 `anthropic` 时，跳过格式转换，原样透传：

```
request.body() → 获取原始 JSON（保留 tools/tool_use 等全部字段）
  │
  ├─ 仅替换 body["model"]（通过 model_mapping）
  ├─ 设置上游 headers: x-api-key + anthropic-version + 透传 anthropic-beta
  │
  ├─ 非流式: provider.send_anthropic_passthrough()
  │   ├─ httpx POST → 上游 /v1/messages
  │   ├─ 从响应提取 usage.input_tokens / output_tokens / cache_read_input_tokens
  │   └─ 返回原始 Anthropic JSON（含 tool_use、thinking 等）
  │
  └─ 流式: StreamingResponse(_passthrough_stream_generator())
      ├─ provider.stream_anthropic_passthrough() → 逐行 yield 原始 Anthropic SSE
      ├─ 从 message_start 提取 input_tokens，从 message_delta 提取 output_tokens
      └─ finally: 计费 + 扣费 + 写日志 + 释放并发 + 关闭连接
```

> **适用场景**: Claude Code（需要 tool_use）、DeepSeek Anthropic 端点、Anthropic 官方 API。完整支持 tool_use、thinking、streaming 等所有 Anthropic 原生特性。

##### 路径 C：Anthropic 格式转换（`/v1/messages` + `provider≠anthropic`）

**文件**: `routers/anthropic_proxy.py`，`services/anthropic_compat.py`

当请求通过 `/v1/messages` 进入但渠道 provider 为 `openai`/`gemini`/`qwen` 时，做 Anthropic↔OpenAI 双向格式转换：

```
anthropic_to_openai_request(body) → 转为 OpenAI 格式
  │
  ├─ 非流式: provider.send_request() → openai_to_anthropic_response() → JSON
  └─ 流式:   stream_proxy() → openai_stream_to_anthropic_stream() → SSE
```

> **限制**: 此路径仅支持纯文本对话，不支持 tool_use。

##### 通用后置逻辑（所有路径共享）

```
提取 usage: prompt_tokens, completion_tokens, cached_tokens
apply_model_mapping → 获取实际模型名（用于查价格）
  │
calculate_cost(model_actual, prompt, completion, channel, cached_tokens)
  ├─ 先查 channel.model_pricing（渠道级覆盖定价）
  ├─ 没有 → 查 model_prices 表（全局定价）
  └─ cost = ((prompt - cached) × prompt_price + cached × cached_price + completion × completion_price) / 1M
  │
deduct_quota(api_key.id, cost)
  └─ UPDATE api_keys SET quota_used = quota_used + cost（F() 原子操作）
  │
save_request_log(...)
  └─ INSERT INTO request_logs（记录全部字段，包括 cost、cached_tokens）
  │
finally:
  ├─ concurrency_limiter.release() → Redis DECR
  └─ provider.close() → 关闭 httpx 连接
```

> **关键设计**: 流式路径所有 cleanup 在 generator 的 `finally` 里，而非路由 handler 的 `finally`。原因是 `StreamingResponse` 异步消费 generator，路由 handler 的 `finally` 在 stream 开始消费前就执行了。

#### 第 8 步：响应返回客户端

```
/v1/chat/completions:
  非流式: Content-Type: application/json + X-Request-ID header
  流式:   Content-Type: text/event-stream + Cache-Control: no-cache + X-Accel-Buffering: no

/v1/messages:
  非流式: Content-Type: application/json（原始 Anthropic 格式或转换后的 Anthropic 格式）
  流式:   Content-Type: text/event-stream（原始 Anthropic SSE 或转换后的 Anthropic SSE）
```

### 协议转换

网关对外统一暴露 OpenAI 格式的端点，同时提供 Anthropic 原生兼容端点 `/v1/messages`。由渠道的 `provider` 字段决定使用哪个 Provider 类。

#### OpenAI / Gemini / Qwen — 透传

上游本身是 OpenAI 兼容端点，Provider 仅做：
- 注入上游的 `Authorization: Bearer {channel.api_key}` header
- 通过 `model_mapping` 替换模型名
- 流式请求自动加 `stream_options.include_usage=true`（让上游返回 usage）
- 请求和响应体原样透传
- 从 `usage.prompt_tokens_details.cached_tokens` 提取缓存命中数

#### Anthropic — 两种路径

**路径 A：原生直通（`/v1/messages` → Anthropic 上游）**

当请求通过 `/v1/messages` 进入且渠道 provider 为 `anthropic` 时，使用 **pass-through 直通模式**：
- 从 `request.body()` 获取原始 JSON（保留所有字段，包括 `tools`、`tool_choice`、`tool_use`/`tool_result` content blocks 等）
- 仅替换 `model`（通过 `model_mapping`）和认证 header（`x-api-key`）
- 请求体和响应体原样透传，不做任何格式转换
- 从 Anthropic 响应中提取 `usage.input_tokens`/`output_tokens`/`cache_read_input_tokens` 用于计费
- 完整支持 `tool_use`、`thinking`、`streaming` 等所有 Anthropic 原生特性

适用于：Anthropic 官方 API、DeepSeek Anthropic 端点（`/anthropic`）等所有 Anthropic 兼容上游。

**路径 B：格式转换（`/v1/chat/completions` → Anthropic 上游 或 `/v1/messages` → 非 Anthropic 上游）**

当请求通过 `/v1/chat/completions` 进入且渠道为 Anthropic，或通过 `/v1/messages` 进入但渠道为非 Anthropic provider 时，使用双向转换：

请求方向（`transform_request`）:

| OpenAI 格式 | Anthropic 格式 |
|---|---|
| `messages` 中 role=system 的消息 | 提取为顶级 `system` 参数 |
| `max_tokens`（可选） | 必填，默认 4096 |
| `temperature` | 限制在 [0, 1.0] |
| `stop` (string/array) | `stop_sequences` (array) |
| `Authorization: Bearer xxx` | `x-api-key: xxx` + `anthropic-version: 2023-06-01` |
| `POST /v1/chat/completions` | `POST /v1/messages` |

响应方向（`transform_response`）:

| Anthropic 格式 | OpenAI 格式 |
|---|---|
| `content[{type:"text", text:"..."}]` | `choices[0].message.content` |
| `stop_reason: "end_turn"` | `finish_reason: "stop"` |
| `stop_reason: "max_tokens"` | `finish_reason: "length"` |
| `usage.input_tokens` | `usage.prompt_tokens` |
| `usage.output_tokens` | `usage.completion_tokens` |
| `usage.cache_read_input_tokens` | `usage.prompt_tokens_details.cached_tokens` |

流式方向（`stream_transform`）— Anthropic SSE 事件链转 OpenAI chunk:

| Anthropic 事件 | 处理 |
|---|---|
| `message_start` | 提取 model、input_tokens、cache_read_input_tokens |
| `content_block_delta` (text_delta) | yield `chat.completion.chunk`（delta.content） |
| `message_delta` | yield chunk + usage（含 cached_tokens）+ finish_reason |
| `message_stop` | yield `data: [DONE]` |

> **注意**: 格式转换路径（路径 B）仅支持纯文本对话，不支持 `tool_use`。如需完整 Anthropic 特性（如 Claude Code 的工具调用），请使用 Anthropic provider 直通路径（路径 A）。

### 错误码速查表

| 状态码 | 错误码 | 出现步骤 | 原因 | 排查方向 |
|--------|--------|----------|------|----------|
| 401 | `invalid_api_key` | 第2步 | Key 不存在或 hash 不匹配 | 确认客户端用的是完整 key（不是 prefix） |
| 401 | `key_disabled` | 第2步 | Key 被管理员禁用 | 后台检查 Key 的启用状态 |
| 401 | `key_expired` | 第2步 | Key 已过期 | 后台检查 expires_at |
| 429 | `quota_exceeded` | 第3步 | USD 余额用完 | 后台查看 quota_used vs quota_total |
| 429 | `concurrent_limit` | 第6步 | 同 Key 并发请求超限 | 降低并发或提高 concurrent_limit |
| 403 | `model_not_allowed` | 第4步 | Key 的 allowed_models 不含该模型 | 后台编辑 Key 添加模型 |
| 404 | `model_not_found` | 第5步 | 没有启用的渠道支持该模型 | 后台检查渠道 models 列表和 is_enabled |
| 500 | `unsupported_provider` | 第5步 | 渠道 provider 字段无效 | 后台检查渠道 provider 拼写 |
| 502 | `upstream_error` | 第7步 | 上游 API 返回错误或超时 | Logs 页面查看 error_message 字段 |

### 日志追踪方法

1. 从响应头获取 `X-Request-ID`
2. 管理后台 → Logs → 搜索该 request_id
3. 日志记录字段：请求模型 / 实际模型 / 渠道 / Provider / Input Tokens / Output Tokens / Cached Tokens / 费用 / 延迟 / 状态码 / 错误信息 / IP / 是否流式

### 渠道选择策略（`registry.py`）

1. 查询所有 `is_enabled=True` 的渠道
2. 过滤 `models` JSON 数组中包含请求模型的渠道
3. 按 `priority` 降序排序
4. 最高优先级组内按 `weight` 加权随机选择
5. 通过 `model_mapping` 将客户端模型名映射为实际模型名

示例: 客户端请求 `gpt-4`，渠道 `model_mapping` 配置 `{"gpt-4": "gpt-4o"}`，实际发送 `gpt-4o` 到上游。

### 并发限制（`services/concurrency.py`）

基于 Redis Lua 脚本实现原子操作：
- **acquire**: `INCR` key，超限则 `DECR` 回退 + 拒绝。首次 `INCR` 设置 TTL=120s 防止泄漏
- **release**: `DECR` key，负数则重置为 0
- Key 格式: `five:concurrency:{api_key_id}`

### API Key 安全模型

- 完整的 `sk-xxx` 密钥仅在创建时返回一次
- 数据库只存 SHA-256 哈希（`key_hash` 字段）
- 管理后台只展示前缀（`key_prefix`，前 8 字符）
- 认证时: 提取 Bearer token → 计算 SHA-256 → 查表匹配

---

## 数据模型

### admins（管理员）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| username | varchar(64) UNIQUE | |
| hashed_password | varchar(255) | bcrypt |
| is_active | bool | 默认 true |
| created_at / updated_at | datetime | 自动管理 |

### channels（上游渠道）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) | 显示名 |
| provider | varchar(32) | `openai` / `anthropic` / `gemini` / `qwen` |
| base_url | varchar(512) | 上游 API 地址 |
| api_key | varchar(512) | 上游密钥 |
| models | JSON | 支持的模型列表 `["gpt-4o", "gpt-4o-mini"]` |
| model_mapping | JSON | 别名映射 `{"gpt-4": "gpt-4o"}` |
| model_pricing | JSON | 渠道级定价覆盖 `{"gpt-4o": {"prompt": 2.5, "completion": 10.0, "cached": 1.25}}`（$/1M tokens）|
| priority | int | 高优先。同模型多渠道时，先选高优先级 |
| weight | int | 同优先级加权随机 |
| is_enabled | bool | |
| timeout | int | 秒 |

### api_keys

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) | 标签，如 "张三的Key" |
| key_hash | varchar(64) UNIQUE | SHA-256 哈希 |
| key_prefix | varchar(12) | 前 8 字符用于展示 |
| quota_total | decimal(16,6) | -1 = 无限，USD 金额 |
| quota_used | decimal(16,6) | 已消耗金额（USD） |
| concurrent_limit | int | 最大并发请求数，默认 5 |
| allowed_models | JSON | 空列表 = 允许所有模型 |
| is_enabled | bool | |
| quota_reset_day | smallint | 每月重置日（1~31），null = 不自动重置 |
| quota_last_reset_at | datetime | 上次自动重置时间 |
| expires_at | datetime | null = 永不过期 |

### request_logs（请求日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | bigint PK | |
| request_id | varchar(36) | UUID，索引 |
| api_key_id / api_key_name | | 反范式存储 |
| channel_id / channel_name | | 反范式存储 |
| model_requested / model_actual | varchar(64) | mapping 前后的模型名 |
| prompt_tokens | int | 输入 token 数 |
| completion_tokens | int | 输出 token 数 |
| total_tokens | int | 总 token 数 |
| cached_tokens | int | 缓存命中 token 数（Prompt Cache） |
| cost | decimal(16,6) | 本次请求费用（USD） |
| is_stream | bool | |
| status_code | int | 上游响应码 |
| latency_ms | int | |
| error_message | text | |
| ip_address | varchar(45) | |

### model_prices（全局模型定价）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| model | varchar(64) UNIQUE | 模型名称，如 `gpt-4o` |
| prompt_price | decimal(16,6) | Prompt 输入单价（$/1M tokens） |
| completion_price | decimal(16,6) | Completion 输出单价（$/1M tokens） |
| cached_price | decimal(16,6) | 缓存命中单价（$/1M tokens），默认 0 |
| currency | varchar(8) | 默认 `USD` |
| is_active | bool | 默认 true |
| created_at / updated_at | datetime | 自动管理 |

### 计费机制

每次请求完成后计算费用并从 Key 的 USD 余额中扣减：

```
non_cached = prompt_tokens - cached_tokens
cost = (non_cached × prompt_price + cached_tokens × cached_price + completion_tokens × completion_price) / 1,000,000
```

**缓存命中折扣**：不同提供商的缓存命中价格差异较大：
- Anthropic: 缓存命中约为 Prompt 价格的 10%
- OpenAI: 缓存命中约为 Prompt 价格的 25%~50%
- Gemini / DeepSeek: 缓存命中约为 Prompt 价格的 25%

**定价优先级**:
1. Channel 的 `model_pricing` JSON 字段（渠道级覆盖定价，含 `prompt` / `completion` / `cached` 三个价格）
2. `model_prices` 全局定价表

**内置价格表**: `services/pricing.py` 中的 `DEFAULT_MODEL_PRICES` 包含约 49 个主流模型（OpenAI GPT-5.x/4.x/o-series、Anthropic Claude 4.x/3.x、Google Gemini 2.x/1.5、Qwen3/2、DeepSeek）的 prompt / completion / cached 三个价格。可通过管理后台 Model Pricing 页面的 "Sync Defaults" 按钮一键导入。

**配额检查**: 请求前检查 `quota_used < quota_total`（`quota_total = -1` 表示无限制）
**扣减方式**: 使用 Tortoise ORM 的 `F()` 表达式实现原子扣减，避免并发竞争

---

## API 参考

### OpenAI 兼容代理（需 API Key 认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | Chat 补全（支持 stream=true） |
| POST | `/v1/completions` | 传统补全（支持 stream=true） |
| POST | `/v1/embeddings` | 向量嵌入 |
| GET | `/v1/models` | 列出当前 Key 可用的模型 |

认证方式: `Authorization: Bearer sk-xxxxx`

请求示例：
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

流式请求：
```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

错误响应格式（统一 OpenAI 风格）：
```json
{
  "error": {
    "message": "Spending quota exceeded",
    "type": "rate_limit_error",
    "code": "quota_exceeded"
  }
}
```

### Anthropic 兼容代理（需 API Key 认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/messages` | Anthropic Messages API（支持 stream=true） |

认证方式: `x-api-key: sk-xxxxx`（也支持 `Authorization: Bearer sk-xxxxx`）

使用与 OpenAI 代理相同的 API Key，共享配额、并发限制和模型权限。

请求示例：
```bash
curl http://localhost:8000/v1/messages \
  -H "x-api-key: sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

流式请求：
```bash
curl -N http://localhost:8000/v1/messages \
  -H "x-api-key: sk-your-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-4-6",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

错误响应格式（Anthropic 风格）：
```json
{
  "type": "error",
  "error": {
    "type": "rate_limit_error",
    "message": "Spending quota exceeded"
  }
}
```

**实现原理**:
- 当上游渠道 provider 为 `anthropic` 时，使用 **pass-through 直通模式**：请求体原样透传到上游 Anthropic 兼容端点，仅替换认证信息和模型名。完整支持 `tool_use`、`thinking`、`streaming` 等所有 Anthropic 原生特性。
- 当上游渠道 provider 为 `openai`/`gemini`/`qwen` 时，在 HTTP 边界做 Anthropic↔OpenAI 格式双向转换（仅支持纯文本对话）。

两种路径均复用全部现有管线（渠道路由、配额、并发、计费、日志），不需要额外配置。

#### Claude Code 直连配置

```bash
# 方式一：环境变量
export ANTHROPIC_BASE_URL=http://your-gateway:8000
export ANTHROPIC_API_KEY=sk-your-five-api-key

# 方式二：Claude Code settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://your-gateway:8000",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-five-api-key"
  }
}
```

> **推荐**：Claude Code 使用 tool_use 进行代码编辑，必须配合 `provider: "anthropic"` 的渠道（如 Anthropic 官方、DeepSeek Anthropic 端点）才能完整工作。使用 `provider: "openai"` 的渠道只能进行纯文本对话。

### 管理后台 API（需 JWT 认证）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/login` | 登录 → `{access_token}` |
| GET | `/api/admin/me` | 当前管理员信息 |
| PUT | `/api/admin/password` | 修改密码 |
| GET/POST | `/api/admin/channels` | 渠道列表(分页) / 创建 |
| GET/PUT/DELETE | `/api/admin/channels/{id}` | 渠道详情 / 更新 / 删除 |
| POST | `/api/admin/channels/{id}/test` | 测试渠道连通性 |
| GET/POST | `/api/admin/keys` | Key列表(分页) / 创建(返回一次明文) |
| GET/PUT/DELETE | `/api/admin/keys/{id}` | Key详情 / 更新 / 删除 |
| POST | `/api/admin/keys/{id}/reset-quota` | 重置已用配额 |
| GET/POST | `/api/admin/model-prices` | 模型定价列表(分页) / 创建 |
| GET/PUT/DELETE | `/api/admin/model-prices/{id}` | 定价详情 / 更新 / 删除 |
| GET | `/api/admin/model-prices/defaults` | 返回内置价格列表（不写库，仅参考） |
| POST | `/api/admin/model-prices/sync-defaults` | 批量导入内置价格（已有的不覆盖） |
| GET | `/api/admin/model-prices/unpriced` | 查询渠道中未设置价格的模型列表 |
| GET | `/api/admin/logs` | 日志列表(分页+过滤) |
| GET | `/api/admin/logs/{request_id}` | 单条日志详情 |
| GET | `/api/admin/stats/overview` | 总览统计 |
| GET | `/api/admin/stats/usage?days=7` | 时序用量 |
| GET | `/api/admin/stats/by-model?days=7` | 按模型统计 |
| GET | `/api/admin/stats/by-key?days=7` | 按 Key 统计 |

分页参数: `?page=1&size=20`
日志过滤参数: `?api_key_id=1&model=gpt-4o&status_code=200&start_date=...&end_date=...`

---

## 配置说明

所有配置通过环境变量或 `.env` 文件管理：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | `change-me` | JWT 签名密钥，**必须修改** |
| `JWT_ALGORITHM` | `HS256` | JWT 算法 |
| `JWT_EXPIRE_MINUTES` | `1440` | JWT 过期时间（分钟），默认 24 小时 |
| `MYSQL_HOST` | `127.0.0.1` | Docker 中自动设为 `mysql` |
| `MYSQL_PORT` | `3306` | |
| `MYSQL_USER` | `five` | |
| `MYSQL_PASSWORD` | `five_password` | |
| `MYSQL_DATABASE` | `five_api` | |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Docker 中自动设为 `redis://redis:6379/0` |
| `INIT_ADMIN_USERNAME` | `admin` | 首次启动创建的管理员用户名 |
| `INIT_ADMIN_PASSWORD` | `admin123` | 首次启动创建的管理员密码，**建议修改** |

Docker Compose 额外变量（仅根目录 `.env`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYSQL_ROOT_PASSWORD` | `root_password` | MySQL root 密码 |
| `BACKEND_PORT` | `8000` | 后端映射到宿主机的端口 |
| `FRONTEND_PORT` | `80` | 前端映射到宿主机的端口 |
| `REDIS_PORT` | `6379` | Redis 映射到宿主机的端口 |

配置加载优先级: 环境变量 > `.env` 文件 > 默认值

---

## 使用流程

### 1. 创建渠道

登录管理后台 → Channels → Add Channel：

**OpenAI 示例**:
- Provider: `openai`
- Base URL: `https://api.openai.com`
- API Key: `sk-proj-xxxx`（你的 OpenAI Key）
- Models: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`

**Anthropic Claude 示例**:
- Provider: `anthropic`
- Base URL: `https://api.anthropic.com`
- API Key: `sk-ant-xxxx`
- Models: `claude-sonnet-4-6-20250819`, `claude-haiku-4-5-20251001`

**Google Gemini 示例**（使用 OpenAI 兼容端点）:
- Provider: `gemini`
- Base URL: `https://generativelanguage.googleapis.com/v1beta/openai`
- API Key: 你的 Google AI API Key
- Models: `gemini-2.5-pro`, `gemini-2.5-flash`

**Qwen 示例**（使用 DashScope 兼容端点）:
- Provider: `qwen`
- Base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- API Key: 你的 DashScope Key
- Models: `qwen3-max`, `qwen-plus`, `qwen-turbo`

**DeepSeek 示例**（使用 Anthropic 兼容端点，推荐用于 Claude Code）:
- Provider: `anthropic`
- Base URL: `https://api.deepseek.com/anthropic`
- API Key: 你的 DeepSeek API Key
- Models: `deepseek-v4-pro`（或添加别名如 `claude-deepseek-v4-pro`）
- Model Mapping: `{"claude-deepseek-v4-pro": "deepseek-v4-pro"}`（可选，用于 Claude Code 模型名映射）

> DeepSeek 也提供 OpenAI 兼容端点（`https://api.deepseek.com`，provider 设为 `openai`），但 OpenAI 端点不支持 Anthropic tool_use 协议，仅适用于 `/v1/chat/completions` 的纯文本对话。

### 2. 创建 API Key

Channels → API Keys → Create Key：
- 设置名称、USD 配额（-1 = 无限，如 10 表示 $10）、最大并发数
- 创建后弹窗显示完整 Key（`sk-xxx`），**仅此一次**，请立即复制保存

### 3. 配置模型定价

Model Pricing → **Sync Defaults**（推荐）：
- 点击 "Sync Defaults" 按钮一键导入内置的 49 个主流模型价格（含 prompt / completion / cached 三个价格）
- 已存在的模型不会被覆盖，只新增缺失的

手动添加:
- 点击 "Add Price"，填写模型名和三个价格（Prompt / Completion / Cached，单位 $/1M tokens）

渠道级覆盖定价:
- 编辑渠道 → Custom Pricing → 为特定模型设置 P（Prompt）/ C（Completion）/ Ca（Cached）价格
- 渠道定价优先于全局定价

未定价提示:
- 页面顶部会显示黄色警告卡片，列出已在渠道中配置但尚未设置价格的模型
- 点击 "添加价格" 可快速跳转到添加表单

### 4. 调用 API

将网关地址当作 OpenAI API 使用：

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-gateway-key",
    base_url="http://your-gateway:8000/v1",
)

response = client.chat.completions.create(
    model="gpt-4o",     # 网关会路由到对应渠道
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

流式：
```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

---

## 开发指南

### 添加新的 Provider

1. 在 `app/providers/` 下创建 `xxx_provider.py`
2. 继承 `BaseProvider`，实现三个抽象方法：
   - `transform_request(openai_request, endpoint)` → `(url_path, headers, body)`
   - `transform_response(provider_response, endpoint)` → OpenAI 格式 dict
   - `stream_transform(response, endpoint)` → 逐行 yield OpenAI SSE 格式
3. 在 `app/providers/registry.py` 的 `PROVIDER_MAP` 中注册

如果新提供商有 OpenAI 兼容端点，可以直接复制 `openai_provider.py`。

### 添加新的管理 API

1. 在 `app/schemas/` 下定义 Pydantic 模型
2. 在 `app/routers/` 下创建路由文件，使用 `Depends(get_current_admin)` 保护
3. 在 `app/main.py` 的 `create_app()` 中注册 router

### 更新内置模型价格

编辑 `backend/app/services/pricing.py` 中的 `DEFAULT_MODEL_PRICES` 字典，添加或更新模型价格条目。格式：

```python
"model-name": {"prompt": 2.5, "completion": 10.0, "cached": 1.25},  # $/1M tokens
```

用户通过管理后台 "Sync Defaults" 按钮将新价格导入数据库（不覆盖已有条目）。

### 前端开发

- Element Plus 组件通过 `unplugin-auto-import` 自动导入，模板中直接使用即可
- 在 `<script setup>` 中需要编程式使用时，显式 `import { ElMessage } from 'element-plus'`
- API 模块在 `src/api/` 下，基于统一的 Axios client（自动附加 JWT、401 自动跳转登录）
- 新增页面: 创建 `views/Xxx.vue` → 在 `router/index.ts` 中添加路由 → 在 `AdminLayout.vue` 侧边栏添加菜单项

### 代码约定

- 后端所有 list 接口返回 `{"total": N, "items": [...]}` 分页格式
- 错误响应统一 OpenAI 格式: `{"error": {"message", "type", "code"}}`
- 认证: 代理路由用 API Key（`verify_api_key`），管理路由用 JWT（`get_current_admin`）
- 异步操作: 所有数据库和 Redis 操作使用 `await`
- Provider cleanup: 非流式在路由 `finally` 中释放并发+关闭 provider；流式在 `stream_proxy` 的 `finally` 中处理

---

## Docker Compose 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| mysql | 3306 | MySQL 8.0，数据持久化到 `mysql_data` named volume |
| redis | 6379 | Redis 7 Alpine，并发限制 + 缓存 |
| backend | 8000 | FastAPI，等待 mysql/redis healthy 后启动 |
| frontend | 80 | 多阶段构建：npm build → Nginx 提供 SPA + 反向代理 |

所有服务配置 `restart: unless-stopped`，异常退出后自动重启。

Nginx 配置要点：
- `/` → SPA fallback（`try_files $uri /index.html`）
- `/api/` → 转发到 `backend:8000`
- `/v1/` → 转发到 `backend:8000`，**关闭 proxy_buffering** 以支持 SSE 流式，300s 超时
- 静态资源 `/assets/` 设置 1 年缓存
- 启用 gzip 压缩

---

## 常见问题

### 首次启动没有管理员？

检查 `.env` 中 `INIT_ADMIN_USERNAME` 和 `INIT_ADMIN_PASSWORD` 是否配置。应用启动时会自动检查 admins 表，为空则创建初始管理员。

### 流式响应不工作？

1. 确认 Nginx 配置了 `proxy_buffering off`（已在 nginx.conf 中设置）
2. 如果在反代后面，确保所有中间层都关闭了 response buffering
3. 检查 `X-Accel-Buffering: no` 响应头是否正确传递

### Token 计费不准确？

- 非流式: 直接使用上游返回的 `usage` 字段
- 流式: OpenAI/Gemini/Qwen 在 `stream_options.include_usage=true` 时最后一个 chunk 包含 usage；Anthropic 从 `message_start`（input_tokens）和 `message_delta`（output_tokens）事件中提取
- 如果上游未返回 usage 信息，tokens 记为 0，cost 为 $0
- 费用计算: `cost = ((prompt - cached) × prompt_price + cached × cached_price + completion × completion_price) / 1M`
- 缓存命中: Anthropic provider 自动将 `cache_read_input_tokens` 映射为 `cached_tokens`；OpenAI 兼容端点从 `prompt_tokens_details.cached_tokens` 提取
- 定价查找顺序: Channel 的 `model_pricing` → 全局 `model_prices` 表
- 如果没有配置任何价格，cost 为 $0（不会阻止请求）

### 缓存命中 token 始终为 0？

- **Anthropic 直连**（provider=`anthropic`）：自动提取 `cache_read_input_tokens`，需要上游启用 prompt caching（发送 `cache_control` 标记）
- **OpenAI 直连**：自动缓存 > 1024 tokens 的 prompt 前缀，第二次相同请求会在 `prompt_tokens_details.cached_tokens` 中返回
- **第三方中转**（provider=`openai` 但 base_url 指向中转）：取决于中转是否透传缓存信息，部分中转不返回 `cached_tokens` 字段

### 渠道测试失败？

- OpenAI/Gemini/Qwen: 测试 `GET /v1/models` 端点
- Anthropic: 测试发送一个最小请求到 `/v1/messages`
- 检查 Base URL 和 API Key 是否正确

### 模型价格从哪里来？

1. **内置价格**：`backend/app/services/pricing.py` 的 `DEFAULT_MODEL_PRICES` 包含 49 个主流模型价格
2. **一键导入**：管理后台 Model Pricing → "Sync Defaults" 按钮
3. **手动添加/编辑**：管理后台直接添加或修改价格
4. **渠道覆盖**：编辑渠道 → Custom Pricing 为特定渠道设置不同价格
