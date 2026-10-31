# 接入 Claude Code、Codex、Cursor

下文的 `https://your-gateway` 换成网关地址（本地为 `http://127.0.0.1:8080`），`sk-...` 换成在「API Key」页面创建的 Key。模型名必须是网关上已配置价格、且有渠道提供的模型，例子用的是 `deepseek-v4-flash`。

实测记录（2026-10-31，Five API 0.4.0 开发版，DeepSeek 官方渠道）：

| 客户端 | 版本 | 结果 |
| --- | --- | --- |
| Claude Code | 2.1.197 | 通过：多轮对话、写文件、执行命令，流式与缓存读取用量按上游计费 |
| Codex CLI | 0.164.0 | 通过：`codex exec` 多轮、执行命令和写文件，按上游用量计费 |
| Cursor | — | 未实测，见下文原因 |

每次实测后都在请求日志里核对了状态码、渠道、上游用量和扣费。

## Claude Code

Claude Code 走 Anthropic 协议的 `/v1/messages`，网关只会把它路由到 **Anthropic 协议**的渠道（如 Anthropic 官方、DeepSeek 的 `https://api.deepseek.com/anthropic`）。只有 OpenAI 协议渠道时 Claude Code 无法使用。

在 `~/.claude/settings.json` 写入（地址不带 `/v1`）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
```

然后直接运行 `claude`。也可以把这些变量 `export` 到环境里，效果相同。

- `ANTHROPIC_MODEL` 和 `ANTHROPIC_DEFAULT_HAIKU_MODEL` 都要设置：Claude Code 默认会用 Claude 模型名做后台小任务，网关上没有这些模型时会返回模型不存在。
- 网关的 Anthropic 渠道直接转发请求，`tool_use`、流式和缓存读写用量都按上游返回计费。
- 只开放部分渠道的 Key（Key 设置了渠道）只能使用其中的 Anthropic 渠道。

## Codex CLI

Codex 0.164 起只支持 Responses 协议（`wire_api = "chat"` 已被 Codex 移除），网关会把 `/v1/responses` 原样转发给 OpenAI 协议的渠道，所以渠道上游必须支持 `/v1/responses`。OpenAI 官方和 DeepSeek 官方实测可用；只支持 Chat Completions 的上游会返回上游错误。

在 `~/.codex/config.toml` 写入（地址带 `/v1`）：

```toml
model = "deepseek-v4-flash"
model_provider = "five"

[model_providers.five]
name = "Five API"
base_url = "https://your-gateway/v1"
env_key = "FIVE_API_KEY"
wire_api = "responses"
```

运行前设置 Key：

```bash
export FIVE_API_KEY=sk-...
codex
```

Codex 在收到 `response.completed` 后立即断开连接，网关会把这种请求记为成功（0.4.0 及以前记为 499，扣费不受影响）。

## Cursor

Cursor 设置 → Models → API Keys，打开「OpenAI API Key」填入 `sk-...`，打开「Override OpenAI Base URL」填 `https://your-gateway/v1`，再在模型列表里添加网关上的模型名（如 `deepseek-v4-flash`）。

**未实测原因**：Cursor 的自定义地址由 Cursor 的服务器发起请求，而不是从你的电脑发起，所以网关必须有公网可访问的 HTTPS 地址，`localhost`、内网地址都不能用。我们的测试环境没有公网地址，因此未做端到端验证。Cursor 的 Agent、Tab 补全等功能是否会走自定义地址由 Cursor 决定，以 Cursor 官方说明为准。

## 常见问题

| 现象 | 原因 |
| --- | --- |
| 401 | Key 填错、已撤销或已过期 |
| 403 | 模型不在这个 Key 的允许范围，或租户已停用 |
| 404 `model_not_found` | 没有提供该模型的对应协议渠道：Claude Code 需要 Anthropic 渠道；Key 限定了渠道时只在这些渠道里找 |
| 429 | 额度用完（`quota_exceeded`）或超过每分钟请求、token、并发限制 |
| 本地网关连不上 | 系统设置了 HTTP 代理时，把网关地址加入 `NO_PROXY` |
