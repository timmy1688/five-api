# Five API Gateway — 接入指南

本文档介绍如何将 Five API Gateway 接入 **Claude Code CLI** 和 **OpenAI Codex CLI**。

---

## 前置准备

确保你已在 Five API 管理后台完成：

1. **创建渠道** — 至少配置一个上游渠道（OpenAI / Anthropic / Gemini / Qwen）
2. **配置模型定价** — 在 Pricing 页面为使用的模型设置价格
3. **创建 API Key** — 获取 `sk-xxx` 格式的 Key（仅在创建时展示一次）

假设你的网关地址为 `https://your-gateway.com`（本地开发则为 `http://localhost:8000`）。

---

## 接入 Claude Code CLI

> Claude Code CLI 使用 **Anthropic 原生协议**（`/v1/messages`），包括 `tool_use` 工具调用。
> Five API 支持两种模式：当上游渠道 provider 为 `anthropic` 时使用 **pass-through 直通**（推荐，完整支持 tool_use）；当上游为 `openai` 等其他 provider 时做格式转换（仅支持纯文本对话）。

### 方式一：环境变量（临时）

```bash
export ANTHROPIC_BASE_URL="https://your-gateway.com"
export ANTHROPIC_AUTH_TOKEN="sk-your-five-api-key"
claude
```

说明：
- `ANTHROPIC_BASE_URL` — 指向你的网关地址（**不要**带 `/v1` 后缀，Claude Code 会自动拼接）
- `ANTHROPIC_AUTH_TOKEN` — 使用 Bearer token 认证，Five API 的 `sk-xxx` Key 即为 Bearer token

### 方式二：配置文件（推荐，持久化）

编辑 `~/.claude/settings.json`：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-five-api-key"
  }
}
```

### 方式三：VS Code 扩展

在 VS Code 的 `settings.json` 中添加：

```json
{
  "claudeCode.environmentVariables": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-five-api-key"
  }
}
```

### 指定模型

Claude Code 默认使用 Sonnet 模型。可通过以下方式切换：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-five-api-key",
    "ANTHROPIC_MODEL": "claude-sonnet-4-20250514"
  }
}
```

也可以使用 Five API 的模型别名功能 — 在渠道的 Model Mapping 中配置别名映射。

### 验证连接

启动 Claude Code 后，输入 `/status` 命令查看当前连接状态，确认 API 端点和认证方式正确。

### 使用第三方模型（如 DeepSeek）

Five API 支持将任何提供 Anthropic 兼容端点的模型接入 Claude Code。以 DeepSeek 为例：

1. 创建渠道：Provider = `anthropic`，Base URL = `https://api.deepseek.com/anthropic`
2. 配置 Model Mapping：`{"claude-deepseek-v4-pro": "deepseek-v4-pro"}`
3. 在 Claude Code settings.json 中将模型名指向别名：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-your-five-api-key",
    "ANTHROPIC_MODEL": "claude-deepseek-v4-pro"
  }
}
```

网关会透传完整的 Anthropic 请求（含 tool_use）到 DeepSeek 的 Anthropic 兼容端点，Claude Code 的工具调用功能正常工作。

### 注意事项

- Claude Code 会向 `/v1/messages` 发送 Anthropic 格式请求（含 `tool_use` 工具调用）
- **推荐使用 `provider: "anthropic"` 的渠道**（pass-through 直通模式），完整支持 tool_use、thinking 等 Anthropic 原生特性
- 使用 `provider: "openai"` 等非 Anthropic 渠道时，网关做格式转换，**仅支持纯文本对话**，不支持工具调用
- `ANTHROPIC_AUTH_TOKEN`（Bearer token）优先级高于 `ANTHROPIC_API_KEY`（X-Api-Key header）
- 确保渠道的 models 列表包含 Claude Code 使用的模型名

---

## 接入 OpenAI Codex CLI

> Codex CLI 支持 OpenAI Chat Completions 协议，与 Five API 的 `/v1/chat/completions` 端点完全兼容。

### 方式一：环境变量（临时）

```bash
export OPENAI_BASE_URL="https://your-gateway.com/v1"
export OPENAI_API_KEY="sk-your-five-api-key"
codex "your prompt here"
```

### 方式二：配置文件（推荐）

编辑 `~/.codex/config.toml`：

```toml
model = "gpt-4o"
model_provider = "five-api"

[model_providers.five-api]
name = "Five API Gateway"
base_url = "https://your-gateway.com/v1"
wire_api = "chat"
env_key = "FIVE_API_KEY"
```

然后设置环境变量：

```bash
export FIVE_API_KEY="sk-your-five-api-key"
codex "refactor the auth module"
```

### 配置说明

| 配置项 | 说明 |
|--------|------|
| `model` | 请求的模型名称，需在网关渠道中配置支持 |
| `model_provider` | 自定义 provider 名称（不要用 `openai`，这是保留名） |
| `base_url` | 网关地址，**需要**带 `/v1` 后缀 |
| `wire_api` | 必须设为 `"chat"`（Chat Completions 协议） |
| `env_key` | 存放 API Key 的环境变量名 |

### 使用不同模型

Codex 支持通过命令行切换模型：

```bash
# 使用 GPT-4o
codex -m gpt-4o "explain this code"

# 使用 Claude（通过网关路由）
codex -m claude-sonnet-4-20250514 "write tests for auth.py"
```

前提：Five API 中已创建支持对应模型的渠道。

### 注意事项

- `wire_api` 必须设为 `"chat"`，Five API 提供的是 Chat Completions 端点
- 不要创建 `[model_providers.openai]`，这是 Codex 内置保留名，会被忽略。使用自定义名称如 `five-api`
- Codex 默认使用 Responses API (`"responses"`)，不设 `wire_api = "chat"` 会导致请求格式不兼容

---

## 接入其他 OpenAI 兼容客户端

Five API 兼容所有使用 OpenAI SDK 的客户端，通用接入方式：

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-five-api-key",
    base_url="https://your-gateway.com/v1",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

### Node.js (openai SDK)

```typescript
import OpenAI from 'openai';

const client = new OpenAI({
  apiKey: 'sk-your-five-api-key',
  baseURL: 'https://your-gateway.com/v1',
});

const response = await client.chat.completions.create({
  model: 'gpt-4o',
  messages: [{ role: 'user', content: 'Hello' }],
});
console.log(response.choices[0].message.content);
```

### cURL

```bash
curl https://your-gateway.com/v1/chat/completions \
  -H "Authorization: Bearer sk-your-five-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

---

## 常见问题

### Claude Code 报 404？

- 检查 `ANTHROPIC_BASE_URL` 是否带了多余的 `/v1` — Claude Code 会自动拼接路径
- 确保网关渠道中有 `anthropic` 类型的渠道，且 models 包含请求的模型

### Codex 报请求格式错误？

- 确认 `wire_api = "chat"` 已设置
- 确认 `base_url` 带了 `/v1` 后缀

### 如何确认请求走了网关？

在 Five API 管理后台的 Logs 页面可以看到所有经过网关的请求记录，包括模型、Token 用量、费用和延迟。
