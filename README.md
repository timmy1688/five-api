# Five API Gateway

极简、易于二次开发的 AI API 网关，为团队内部共享 LLM 资源而生。

统一管理多个上游提供商的 API Key，对内分发独立配额的网关 Key，按 token 用量自动计费。对外暴露 **OpenAI 兼容接口**和 **Anthropic 原生接口**，接入方零改造。

## 核心优势

### Anthropic 原生直通 — Claude Code 开箱即用

对 Anthropic 协议做了**原生直通**（passthrough），请求体原样透传到上游，完整保留 `tool_use`、`thinking`、`streaming`、`prompt-caching`、`extended-cache-ttl`、`interleaved-thinking` 等所有 Anthropic 原生特性和 Beta 功能。

```bash
# 两行配置，Claude Code 直连网关
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=sk-your-gateway-key
```

### 协议自动转换 — 一套 Key 通吃所有模型

**双向协议转换**：Anthropic 客户端可以透明调用 OpenAI 兼容模型（含 Gemini/Qwen 等），反之亦然。网关自动处理请求和响应的格式转换，包括流式传输，以及 **工具调用（tool_use ↔ tool_calls）的全链路双向转换**（含多轮 tool_result 往返与流式工具参数）。

**协议优先路由**：`/v1/messages` 请求优先匹配 Anthropic 渠道（原生直通），`/v1/chat/completions` 优先匹配 OpenAI 兼容渠道。不匹配的渠道作为故障转移备选，确保最大可用性。

### USD 级精准计费 — 含 Prompt Cache 折扣

区分三种价格精确计费：

- **Prompt 价格** — 普通输入 token
- **Cached 价格** — 缓存命中 token（通常是 prompt 价格的 10%~50%）
- **Completion 价格** — 输出 token

自动识别各提供商的缓存命中字段（Anthropic 的 `cache_read_input_tokens`、OpenAI 的 `prompt_tokens_details.cached_tokens`），费用精确到美元小数点后 6 位。内置 **57 个**主流模型价格，一键导入。支持渠道级定价覆盖。

### 智能故障转移 + 自动熔断

同一模型配置多个渠道时，按**优先级分层 + 权重加权随机**选择。上游 5xx / 超时 / 网络错误时自动切换下一个渠道，对客户端透明。流式请求在尚未发送数据时也支持故障转移。

后台定期**主动健康探测**所有渠道，连续失败自动熔断（阈值可配置），避免将请求发送到已知故障的渠道。支持管理后台手动恢复。

### 完整的 RBAC 权限管理

基于角色的细粒度权限控制，覆盖 8 大资源（渠道、Key、模型分组、定价、日志、统计、用户、角色）共 **16 个权限点**。内置 Super Admin（全权限）和 Viewer（只读）两个角色，支持自建角色自由组合权限。

前端三层权限控制：菜单显隐 → 按钮显隐 → 路由守卫，后端是唯一安全屏障。

### 代码量小，真正可控

后端约 5000 行 Python，前端约 3000 行 Vue，没有过度抽象。整个请求链路（认证 → 配额 → 路由 → 转发 → 计费）在 CLAUDE.md 里有完整的逐步说明。出了问题能 debug，想加功能能动手。

## 与同类项目的区别

市面上有 One API、New API 等方案，Five API 选择了不同的取舍：

| | Five API | 同类项目 |
|---|---|---|
| 代码规模 | ~5000 行后端 + ~3000 行前端 | 通常 2~5 万行 |
| 二次开发 | 加一个 Provider 实现 3 个方法 | 需要理解大量抽象层 |
| Anthropic 支持 | 原生直通 + Beta 特性透传 | 通常走格式转换，丢失原生特性 |
| 协议转换 | 双向自动转换（Anthropic ↔ OpenAI） | 多为单向 |
| 计费精度 | 区分 prompt / completion / cached 三种价格 | 部分不区分缓存价格 |
| 权限管理 | RBAC 角色权限 + 16 个权限点 | 简单管理员分级 |
| 可观测性 | Prometheus 指标 + 8 维统计 + 请求追踪 | 基础统计 |
| 技术栈 | Python + Vue 3，主流且现代 | 部分使用 Go + React，学习曲线不同 |

一句话：**够用、好懂、好改**。

## 为什么需要它

团队里多人共用几个 LLM API Key 时，常见的痛点：

- **费用不透明** — 不知道谁用了多少、花了多少钱
- **Key 泄露风险** — 上游 Key 直接分发给每个人，一旦泄露影响所有人
- **没有用量限制** — 某人跑了个循环把额度烧光，其他人无法使用
- **多提供商切换麻烦** — 想从 OpenAI 切到 Claude 或 Gemini，每个客户端都要改

Five API 的做法：上游 Key 只存在网关里，每个人拿到的是网关分发的独立 Key，各自有 USD 配额、并发限制、模型权限。接入方只需改一个 base_url，不感知后端切了什么提供商。

## 功能全景

### 多提供商支持

| Provider | 说明 |
|----------|------|
| **OpenAI** | GPT-5.x / GPT-4.x / o 系列推理模型，透传 |
| **Anthropic** | Claude 4.x / 3.x，原生直通 + Beta 特性 |
| **Google Gemini** | Gemini 3.x / 2.x / 1.5，OpenAI 兼容端点（`provider=openai`） |
| **Alibaba Qwen** | 通义千问全系列，DashScope 兼容端点（`provider=openai`） |
| **DeepSeek** | 通过 OpenAI 兼容端点或 Anthropic 端点接入 |

支持任何 OpenAI 兼容的第三方中转站。

### 代理端点

| 端点 | 说明 |
|------|------|
| `POST /v1/chat/completions` | OpenAI Chat Completions（含流式） |
| `POST /v1/completions` | OpenAI Legacy Completions |
| `POST /v1/embeddings` | 向量嵌入 |
| `POST /v1/messages` | Anthropic Messages（含流式） |
| `GET /v1/models` | 当前 Key 可用模型列表 |
| `GET /v1/me` | Key 配额 / 可用模型 / 模型定价自查 |

完整透传客户端参数，包括 `tools`、`tool_choice`、`response_format` 等。

### Key 管理

- **USD 配额** — 每个 Key 独立额度，-1 表示无限
- **月度自动重置** — 配置每月重置日（1~31），自动重置已用额度
- **并发限制** — Redis 原子计数，120s 安全自动释放
- **RPM 限速** — Redis + Lua 脚本原子限流
- **模型分组** — 创建命名的模型集合，批量分配给多个 Key，统一管理
- **模型白名单** — 直接在 Key 上指定允许的模型（模型分组优先）
- **IP 白名单** — 支持 CIDR 子网表示法
- **过期时间** — 到期自动失效
- **安全存储** — SHA-256 哈希存储，明文仅创建时返回一次

### 路由与故障转移

- **优先级 + 权重** — 高优先级渠道先选，同级按权重加权随机
- **协议优先路由** — 根据请求协议自动匹配最优渠道
- **自动故障转移** — 5xx / 超时 / 网络错误自动切换备选渠道
- **流式故障转移** — 未发送数据前仍可切换渠道
- **自动熔断** — 连续失败达阈值后自动隔离（阈值可配置）
- **主动健康探测** — 后台定期检测所有渠道状态
- **手动恢复** — 管理后台一键恢复被熔断的渠道
- **模型别名映射** — 渠道级模型名映射（如 `gpt-4` → `gpt-4o`）

### 计费系统

- **三级定价** — Prompt / Completion / Cached 分别定价
- **定价优先级** — 渠道级覆盖 → 全局价格表 → $0（不阻止请求）
- **内置 57 个模型价格** — 一键导入，覆盖 OpenAI / Claude / Gemini / Qwen / DeepSeek
- **未定价模型检测** — 自动发现缺少定价的模型
- **原子扣费** — F() 表达式确保并发安全

### 可观测性

- **Prometheus `/metrics`** — 请求计数、Token 计数、费用计数、延迟直方图、活跃渠道/Key 数
- **请求追踪** — `X-Request-Id` 全链路透传，支持端到端追踪
- **8 维统计分析**：
  - 总览（请求数、Token、费用、今日数据）
  - 每日用量趋势（最多 90 天）
  - 按模型 / Key / 渠道分维度统计
  - 错误率趋势
  - 延迟 P50 / P95 / P99
  - 实时吞吐量（QPS / RPM / TPM + 历史峰值）
- **请求日志** — 完整记录每次请求的模型、Token、费用、延迟、状态码、IP
- **日志自动清理** — 可配置保留天数（默认 90 天），后台自动批量清理

### 管理后台

Vue 3 + Element Plus 构建的现代化管理界面：

- **Dashboard** — 用量概览 + ECharts 图表
- **Channels** — 渠道管理（健康状态、连通性测试、上游模型拉取）
- **API Keys** — Key 管理（配额、模型分组、配额重置）
- **Model Groups** — 模型分组管理（批量模型权限）
- **Model Pricing** — 定价管理（内置价格同步、未定价模型发现）
- **Models** — 模型汇总视图（跨渠道模型全景）
- **Logs** — 请求日志（多条件筛选、Request ID 查询）
- **Roles** — 角色管理（权限勾选矩阵）
- **Admins** — 管理员管理（角色分配）

## 快速开始

### Docker Compose

```bash
cp .env.example .env
vi .env  # 改 SECRET_KEY 和密码

docker compose up -d

# 管理后台: http://localhost
# 默认账号: admin / admin123 (Super Admin)
```

### 本地开发

```bash
docker compose up -d mysql redis  # 只启动依赖

./service.sh start
# 前端: http://localhost:5001
# 后端: http://localhost:5002
# 日志: ./service.sh logs   (或 logs/backend.log, logs/frontend.log)
# 停止: ./service.sh stop   重启: ./service.sh restart
```

## 使用

**1. 添加渠道** — 管理后台 → Channels → Add Channel

渠道 `provider` 只有 `openai`（OpenAI 兼容端点）和 `anthropic`（Anthropic 原生端点）两种：

| provider | 上游 | Base URL |
|----------|------|----------|
| `openai` | OpenAI 及兼容中转 | `https://api.openai.com` |
| `openai` | Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `openai` | 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `anthropic` | Anthropic Claude | `https://api.anthropic.com` |
| `anthropic` | DeepSeek（Claude Code 推荐） | `https://api.deepseek.com/anthropic` |

**2. 创建 Key** — 设置 USD 配额和并发数，复制生成的 `sk-xxx`（仅显示一次）

**3. 导入价格** — Model Pricing → Sync Defaults，一键导入 57 个主流模型价格

**4. 接入**

```python
# OpenAI 格式
from openai import OpenAI
client = OpenAI(api_key="sk-your-gateway-key", base_url="http://your-server:8000/v1")
resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "Hello"}])
```

```bash
# Anthropic 格式 / Claude Code 直连
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=sk-your-gateway-key
```

```bash
# cURL — Anthropic 流式
curl -N http://your-server:8000/v1/messages \
  -H "x-api-key: sk-your-gateway-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":1024,"stream":true,"messages":[{"role":"user","content":"Hello"}]}'
```

## 请求链路

```
客户端 → Request ID → API Key 认证 → 配额检查 → 模型权限 → RPM 限流
                                                                ↓
  计费扣费 ← 响应返回 ← 协议转换(如需) ← 上游 API ← 并发限制 ← 渠道选择(协议优先)
  日志记录
  释放并发
```

## 计费公式

```
cost = ((prompt - cached) × prompt_price + cached × cached_price + completion × completion_price) / 1M
```

## 技术栈

| 后端 | FastAPI · Tortoise ORM · MySQL · Redis |
|------|---------------------------------------|
| 前端 | Vue 3 · Element Plus · ECharts |
| 部署 | Docker Compose（Nginx + FastAPI + MySQL + Redis） |
| 监控 | Prometheus 指标端点 |

## 项目结构

```
backend/
  app/
    providers/     # 上游适配器（两种线协议：OpenAI 兼容 / Anthropic）
    routers/       # API 路由（代理 + 管理 + 统计 + 指标）
    services/      # 业务逻辑（认证/RBAC/计费/配额/并发/限流/熔断/日志/指标）
    models/        # ORM 模型（User/Role/Channel/APIKey/ModelGroup/ModelPrice/RequestLog）
    schemas/       # Pydantic 请求/响应模型
    middleware/    # Request ID 中间件
    utils/         # 工具函数（Key 生成/IP 检查）
frontend/
  src/
    views/         # 页面（Dashboard/Channels/Keys/Groups/Prices/Models/Logs/Roles/Admins）
    api/           # Axios API 模块
    stores/        # Pinia 状态管理（认证 + 权限）
    router/        # 路由 + 权限守卫
```

## 二次开发

**接入新上游**：系统只有 OpenAI / Anthropic 两种线协议，OpenAI 兼容端点直接建 `provider=openai` 渠道、Anthropic 端点建 `provider=anthropic` 渠道即可，无需写代码。仅当上游是全新原生协议时，才继承 `BaseProvider` 实现 `transform_request` / `transform_response` / `stream_transform`，并在 `registry.py` 注册。

**添加新权限**：`services/auth.py` 的 `ALL_PERMISSIONS` 添加权限 → 更新 `BUILTIN_ROLES` → 路由用 `require_permission()` 保护 → 前端用 `auth.hasPermission()` 控制 UI。

**添加管理页面**：`schemas/` 定义模型 → `routers/` 写路由 → `views/` 写页面 → 注册路由和菜单。

详细架构文档见 [CLAUDE.md](CLAUDE.md)。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | `change-me` | JWT 密钥，**必须修改** |
| `JWT_EXPIRE_MINUTES` | `1440` | JWT 过期时间（分钟） |
| `INIT_ADMIN_USERNAME` | `admin` | 初始管理员用户名 |
| `INIT_ADMIN_PASSWORD` | `admin123` | 初始管理员密码 |
| `MYSQL_HOST` | `127.0.0.1` | MySQL 地址 |
| `MYSQL_PASSWORD` | `five_password` | MySQL 密码 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis 连接地址 |
| `CHANNEL_HEALTH_THRESHOLD` | `3` | 连续失败熔断阈值 |
| `CHANNEL_HEALTH_CHECK_INTERVAL` | `60` | 健康探测间隔（秒） |
| `LOG_RETENTION_DAYS` | `90` | 日志保留天数 |
| `BACKEND_PORT` | `8000` | 后端端口（Docker） |
| `FRONTEND_PORT` | `80` | 前端端口（Docker） |

完整列表见 [.env.example](.env.example)。

## License

MIT
