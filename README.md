# Five API Gateway

极简、易于二次开发的 AI API 网关，为团队内部共享 LLM 资源而生。

统一管理多个上游提供商的 API Key，对内分发独立配额的网关 Key，按 token 用量自动计费。对外暴露 OpenAI 兼容接口和 Anthropic 原生接口，接入方零改造。

## 项目定位

**给谁用**：3~50 人的技术团队，有多个 LLM API Key（OpenAI、Claude、Gemini 等），需要在团队内部安全分发、控费、审计。

**不是什么**：不是企业级 API 管理平台（没有多租户、RBAC 权限树、审批流），不是 LLM 应用框架（不做 RAG、Agent 编排）。它只做一件事——**当好中间那层网关**。

**与同类项目的区别**：市面上有 One API、New API 等方案，Five API 选择了不同的取舍：

| | Five API | 同类项目 |
|---|---|---|
| 代码规模 | ~5000 行后端 + ~3000 行前端 | 通常 2~5 万行 |
| 二次开发 | 加一个 Provider 实现 3 个方法 | 需要理解大量抽象层 |
| Anthropic 支持 | 原生直通，完整支持 tool_use / thinking | 通常走格式转换，丢失原生特性 |
| 计费精度 | 区分 prompt / completion / cached 三种价格 | 部分不区分缓存价格 |
| 技术栈 | Python + Vue 3，主流且现代 | 部分使用 Go + React，学习曲线不同 |

一句话：**够用、好懂、好改**。

## 核心优势

### Anthropic 原生直通 — Claude Code 开箱即用

Five API 对 Anthropic 协议做了**原生直通**（pass-through），不走格式转换。请求体原样透传到上游，完整保留 `tool_use`、`thinking`、`streaming` 等所有 Anthropic 原生特性。这意味着 Claude Code 可以直接连接网关使用，不会因为中间层的格式转换而丢失工具调用能力。

```bash
# 两行配置，Claude Code 直连网关
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=sk-your-gateway-key
```

### USD 级精准计费 — 含 Prompt Cache 折扣

不是简单地按 token 数计费，而是区分三种价格：

- **Prompt 价格** — 普通输入 token
- **Cached 价格** — 缓存命中 token（通常是 prompt 价格的 10%~50%）
- **Completion 价格** — 输出 token

自动识别各提供商的缓存命中字段（Anthropic 的 `cache_read_input_tokens`、OpenAI 的 `prompt_tokens_details.cached_tokens`），费用精确到美元小数点后 6 位。内置 49 个主流模型价格，一键导入。

### 代码量小，真正可控

后端约 5000 行 Python，前端约 3000 行 Vue，没有过度抽象。整个请求链路（认证 → 配额 → 路由 → 转发 → 计费）在 CLAUDE.md 里有完整的逐步说明。出了问题能 debug，想加功能能动手。

### 智能故障转移

同一模型配置多个渠道时，按优先级 + 权重自动选择。上游 5xx / 超时 / 网络错误时自动切换下一个渠道，对客户端透明。流式请求在尚未发送数据时也支持故障转移。

### 每个 Key 独立管控

每个网关 Key 可以独立设置：USD 配额、并发上限、RPM 限制、模型白名单、IP 白名单、过期时间、渠道分组。上游 Key 永远不暴露给使用者。

## 为什么需要它

团队里多人共用几个 LLM API Key 时，常见的痛点：

- **费用不透明** — 不知道谁用了多少、花了多少钱
- **Key 泄露风险** — 上游 Key 直接分发给每个人，一旦泄露影响所有人
- **没有用量限制** — 某人跑了个循环把额度烧光，其他人无法使用
- **多提供商切换麻烦** — 想从 OpenAI 切到 Claude 或 Gemini，每个客户端都要改

Five API 的做法：上游 Key 只存在网关里，每个人拿到的是网关分发的独立 Key，各自有 USD 配额、并发限制、模型权限。接入方只需改一个 base_url，不感知后端切了什么提供商。

## 功能

- **多提供商路由** — OpenAI / Anthropic / Gemini / Qwen / Azure，按优先级 + 权重分配流量
- **双协议** — OpenAI 格式 (`/v1/chat/completions`) + Anthropic 格式 (`/v1/messages`)，Claude Code 直连
- **精准计费** — Prompt / Completion / Cached 三种价格，内置 49 个主流模型价格一键导入
- **Key 隔离** — 每个 Key 独立配额、并发限制、RPM 限制、模型白名单、过期时间
- **自动故障转移** — 上游异常自动切换备选渠道，对客户端透明
- **渠道健康监测** — 自动熔断异常渠道，支持手动恢复
- **管理后台** — 渠道管理、Key 管理、模型定价、用量统计、请求日志、管理员管理
- **易于二次开发** — FastAPI + Vue 3，结构清晰，加一个 Provider 只需实现三个方法

## 快速开始

### Docker Compose

```bash
cp .env.example .env
vi .env  # 改 SECRET_KEY 和密码

docker compose up -d

# 管理后台: http://localhost
# 默认账号: admin / admin123
```

### 本地开发

```bash
docker compose up -d mysql redis  # 只启动依赖

./start.sh
# 前端: http://localhost:5001
# 后端: http://localhost:5002
# 停止: ./stop.sh
```

## 使用

**1. 添加渠道** — 管理后台填入上游提供商的 Base URL 和 API Key

**2. 创建 Key** — 设置 USD 配额和并发数，复制生成的 `sk-xxx`（仅显示一次）

**3. 导入价格** — Model Pricing → Sync Defaults，一键导入主流模型价格

**4. 接入** — 把网关地址当 OpenAI 用：

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-gateway-key",
    base_url="http://your-server:8000/v1",
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
```

Claude Code 直连：

```bash
export ANTHROPIC_BASE_URL=http://your-server:8000
export ANTHROPIC_API_KEY=sk-your-gateway-key
```

## 请求链路

```
客户端 → 认证 → 配额检查 → 模型权限 → 渠道选择 → 并发限制 → 协议转换 → 上游 API
                                                                    ↓
                                                        计费扣费 ← 响应返回
                                                        日志记录
```

## 计费

```
cost = ((prompt - cached) × prompt_price + cached × cached_price + completion × completion_price) / 1M
```

定价优先级：渠道自定义 → 全局价格表 → 未配置则 $0（不阻止请求）

## 技术栈

| 后端 | FastAPI · Tortoise ORM · MySQL · Redis |
|------|---------------------------------------|
| 前端 | Vue 3 · Element Plus · ECharts |
| 部署 | Docker Compose（Nginx + FastAPI + MySQL + Redis） |

## 项目结构

```
backend/
  app/
    providers/     # 上游适配器（OpenAI/Anthropic/Gemini/Qwen）
    routers/       # API 路由（代理 + 管理）
    services/      # 业务逻辑（认证/计费/配额/并发/日志）
    models/        # ORM 模型
    schemas/       # 请求/响应模型
frontend/
  src/
    views/         # 页面组件
    api/           # API 模块
```

## 二次开发

**添加新 Provider**：继承 `BaseProvider`，实现 `transform_request` / `transform_response` / `stream_transform` 三个方法，在 `registry.py` 注册。OpenAI 兼容的端点直接复制 `openai_provider.py`。

**添加管理页面**：`schemas/` 定义模型 → `routers/` 写路由 → `views/` 写页面 → 注册路由和菜单。

详细架构文档见 [CLAUDE.md](CLAUDE.md)。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | `change-me` | JWT 密钥，**必须修改** |
| `INIT_ADMIN_USERNAME` | `admin` | 初始管理员 |
| `INIT_ADMIN_PASSWORD` | `admin123` | 初始密码 |
| `MYSQL_PASSWORD` | `five_password` | 数据库密码 |
| `BACKEND_PORT` | `8000` | 后端端口 |
| `FRONTEND_PORT` | `80` | 前端端口 |

完整列表见 [.env.example](.env.example)。

## License

MIT
