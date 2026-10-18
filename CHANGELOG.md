# Changelog

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。打 `v*` tag 后，GitHub Actions 会把对应段落发成 Release，并推送镜像到 `ghcr.io/timmy1688/five-api`。

## [0.3.0] - 未发布

### 新增

- `/v1/responses`，流式和非流式都透传到 OpenAI 兼容渠道，按 `response.completed` 里的用量计费。
- 图片（`/v1/images/generations`、`edits`、`variations`）、语音（`/v1/audio/speech`、`transcriptions`、`translations`）和 `/v1/rerank`。模型定价和渠道定价新增按次价。
- 团队：共用一笔美元预算，可按月重置。团队内 Key 同时扣自己的额度和团队预算，超出返回 `team_quota_exceeded`，团队停用返回 `team_disabled`。新增权限 `team:read`、`team:write`。
- 渠道选择策略：同优先级内按权重随机、最少进行中请求或最近延迟最低。在系统设置里切换。
- 概览页新增团队用量。
- 渠道号池：一个渠道可填多把上游 Key。429 按 `retry-after` 冷却，401、403 冷却 10 分钟，同一会话固定同一把 Key。
- 模型回退链：一个模型的渠道全部失败后改用下一个模型。在系统设置里配置。
- 滚动限额：Key 和团队可设 5 小时、24 小时、7 天美元上限，错误码 `window_limit`、`team_window_limit`。
- 成本洞察页：缓存命中率、缓存节省金额、按会话的花费。日志记录会话 ID、缓存节省和费用明细。
- 接入指南页：Claude Code、Codex、Cursor、OpenAI 和 Anthropic SDK 的配置。
- 自动缓存：Anthropic 请求没带 `cache_control` 时自动加缓存标记。默认关闭。
- 预算降级：Key 或团队预算用到阈值后，按规则改用便宜模型，响应头带 `x-five-downgraded-to`。
- 账单对账页：上传厂商 CSV，按天和模型对比网关计费。新增 `POST /api/reconcile`。
- 分时定价：指定时段、模型和渠道的费用乘以倍率。
- 告警：飞书、钉钉、企业微信和 JSON Webhook，覆盖预算阈值、渠道熔断与恢复、5xx 占比。新增 `/api/settings/alerts`。

### 变更

- MySQL 和 Redis 端口只绑 `127.0.0.1`。镜像只信任本机发来的 `X-Forwarded-For`。
- 镜像构建固定走国内源（pip 用阿里云，npm 用 npmmirror），去掉 `PIP_INDEX_URL`、`NPM_REGISTRY` 构建参数。
- 流式请求中途断开或上游没给用量时，按已转发的内容估算 token 计费，不再记 0。
- 改密码、管理员被改密码或停用后，旧的登录凭证立即失效。
- 同一 IP 或用户名 15 分钟内登录失败 10 次，暂停登录 15 分钟。
- 统计接口改读按天汇总表，不再扫描整张请求日志。

### 升级

- 新增迁移 `14_add_teams_usage_daily_routing`，容器启动时自动执行，并用已有日志回填按天汇总。
- 新增迁移 15～17：渠道 Key 改为长文本，Key 和团队加滚动限额，日志和按天汇总加会话、缓存节省和费用明细。缓存节省只从升级后的请求开始累计。
- 外部机器原来直连 3306 或 6379 的，改走 SSH 隧道，或自行改回 `docker-compose.yml` 的端口绑定。

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
- 构建参数 `PIP_INDEX_URL`、`NPM_REGISTRY` 可以换成国内镜像源，默认仍是官方源。

### 升级

- 新增迁移 `13_add_key_tpm_limit`，容器启动时自动执行。
- 在后台「模型定价」点一次「同步最新价格」，刷新已有的缓存写入价和 DeepSeek 价格。

## [0.1.0] - 2026-10-11

首个公开版本：OpenAI / Anthropic 双协议网关，Anthropic 原生透传，渠道故障转移和熔断，粘性会话，Key 美元额度、RPM、并发和 IP 白名单，模型分组，RBAC 管理后台，关键词和密钥扫描，推理审计。
