# Changelog

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。打 `v*` tag 后，GitHub Actions 会把对应段落发成 Release，并推送镜像到 `ghcr.io/timmy1688/five-api`。

## [0.2.0] - 2026-10-18

### 新增

- 缓存写入单独计价。Claude 内置价是输入价的 1.25 倍，其他模型与输入价相同。
- 请求前按估算费用预留额度，响应后按实际费用结算。并发请求不会超出额度。
- Key 级 TPM 限制，错误码 `tpm_limit`。
- `/v1/messages/count_tokens`，转发到 Anthropic 渠道，不计费。上游没有这个接口时返回本地估算。
- 上游的限流响应头（`x-ratelimit-*`、`anthropic-ratelimit-*`、`retry-after`、`request-id`）交回客户端。上游的 `x-request-id` 改名为 `x-upstream-request-id`。
- `/healthz` 检查 MySQL 和 Redis。Docker 镜像和 compose 都加了健康检查。
- 后台右上角菜单可以修改密码。
- GitHub Actions：每次提交跑测试和构建，打 tag 发布多架构镜像。

### 变更

- 用默认密码 `admin123` 登录后，必须先改密码，才能调用其他管理接口。
- `/metrics` 默认只允许本机访问。设置 `METRICS_TOKEN` 后，凭 Bearer 令牌远程抓取。
- OpenAI 兼容请求只转发客户端实际传入的字段，不再补 `temperature: null` 这类空值。
- `anthropic-beta` 原样转发，不再按白名单过滤。
- 上游 4xx 且正文是 JSON 时，原样返回状态码和正文，流式请求放进 SSE 错误事件。
- embeddings 的 `input` 和 completions 的 `prompt` 接受 token 数组。
- Anthropic 渠道的 Base URL 可以以 `/v1` 结尾。
- DeepSeek 内置价格更新为官方高峰价，新增 `deepseek-flash`。
- 容器启动时先等 MySQL 和 Redis 就绪再执行迁移，不再依赖自动重启。

### 升级

- 新增迁移 `13_add_key_tpm_limit`，容器启动时自动执行。
- 在后台「模型定价」点一次「同步最新价格」，刷新已有的缓存写入价和 DeepSeek 价格。

## [0.1.0] - 2026-10-11

首个公开版本：OpenAI / Anthropic 双协议网关，Anthropic 原生透传，渠道故障转移和熔断，粘性会话，Key 美元额度、RPM、并发和 IP 白名单，模型分组，RBAC 管理后台，关键词和密钥扫描，推理审计。
