# Changelog

版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。打 `v*` tag 后，GitHub Actions 会把对应段落发成 Release，并推送镜像到 `ghcr.io/timmy1688/five-api`。

## [0.4.0] - 2026-10-31

### 功能

- 固定平台管理员、租户两种角色，单层 Tenant，一个租户一个账号；平台人工开户与额度调整，租户自行管理 Key。
- 首页和 Key 页支持平台自用 Key，自动归内部空间，不代客户创建；账号菜单合并为租户账号、平台管理员。
- 租户共享 RPM、TPM、并发及累计额度；足额预占、报价快照、事务幂等结算、有限重试与未知结果核对。
- 模型广场展示实际计费价、渠道和健康状态；健康默认每 15 分钟，GPT/Claude 降智参考默认每天一次，支持手动检测和结果历史。
- 按渠道定价：模型售价 × 渠道价格倍率，或渠道固定价；租户可在 Key 上选择渠道。参考价导入只补缺失项，保留既有价格与状态。
- 系统设置分组保存、高级规则折叠、手机布局；移除 CSV 账单对账与独立结算恢复页签，异常时才显示核对入口。
- 原生 OpenAI/Anthropic 错误、独立内部请求 ID、缺失用量估算来源、错误/告警/审计凭据脱敏。
- 报价快照对同一模型只查询一次售价，推理请求的 SQL 条数不再随候选渠道数量增长。
- 推理请求在预扣前只读取一次租户，模型授权、选路、预算降级与预扣复用鉴权结果，扣费仍以加锁后的租户与 Key 为准；OpenAI 与 Anthropic 共用一套 Key 鉴权。

### 行为变化

- 上游返回 401/403 时切换到下一个渠道，并计入渠道熔断。最后一个渠道仍失败时，客户收到 502 `Upstream credentials unavailable`，不再透传上游的鉴权错误；原始错误保留在请求日志里。
- 图片生成、编辑、变体与视频创建、续写不再在读超时或上游 5xx 后重发，避免重复出图、重复扣上游费用。只有确认请求没到达上游（连接失败、429、401/403、号池无可用 Key）时才重试或换渠道。
- 号池里的 Key 全部冷却时直接跳过该渠道，不再拿冷却中的 Key 去请求上游；这是最后一个候选渠道时返回 503。
- 滚动限额（5h、1d、7d）和预算降级把在途请求的预占金额一起计算，并发突发不会一起越过上限。只在设置了上限时多查一次 SQL。
- `/v1/me` 返回客户实际计费的售价：基础价乘以倍率，按渠道映射后的模型取价，内置目录价的模型也会列出，未定价模型不列出。`model_prices_source` 改为 `selling_price`，`channel_overrides_may_apply` 改为 false。新增 `tenant_quota_total`、`tenant_quota_used`，`quota_remaining` 改为扣除在途预占后 Key 与租户剩余额度中较小的值。
- 用量统计的按租户排行不再包含内部空间（平台自用 Key）。
- 请求日志的“来源”改名为“错误来源”，上游错误不再区分官网和渠道商，统一记为“渠道商”（`error_origin=channel`）。迁移 23 把历史日志的 `official`、`reseller` 改为 `channel`，回滚时统一回到 `reseller`。
- AI 审计：已有结论（通过、存疑、跳过）的请求不再重复送审，只有未审和上次失败的会调用模型；相同摘录的结论缓存从 10 分钟延长到 7 天；审计页每个 Key 只加载最近 200 条保存请求。移除未接入界面、也从未生效的“审计不可用时拦截请求”（`fail_closed`）设置和未使用的后台审查队列。
- `docker-compose.yml` 的初始管理员账号密码直接写在文件里，不再读取环境变量；只在首次启动时生效，首次登录强制改密码。
- 请求日志页移除“清理”按钮和 `POST /api/logs/cleanup` 接口，日志只按“日志保留天数”设置自动清理（0 表示永久保留）。状态码筛选换成“结果”筛选：成功（状态码 < 400）或只看错误（≥ 400），接口参数 `status_code` 改为 `result=success|error`。
- 计费改为按渠道定价：客户价 = 模型售价 × 渠道“价格倍率”，渠道也可以给单个模型设固定价（固定价是最终价，不再乘倍率；模型售价停用时仍拒绝请求）。每个请求按实际服务的渠道结算，按候选渠道中最贵的报价预占。
- API Key 新增“渠道”选择（`channel_ids`）：不选为全部渠道，与之前一致；选一个渠道即固定价格，该渠道不可用时请求返回 404 不再切换；选多个只在其间故障切换。租户通过 `GET /api/keys/channels` 看到可选渠道的名称、倍率、各模型价格和健康状态，不含上游地址与密钥；不能选择停用、不存在或不服务本租户模型的渠道。被未撤销 Key 选用的渠道不能删除（409）。
- `/v1/me` 只列出 Key 所选渠道的模型，`model_prices` 每个模型给出最高价并在 `channels` 中列出各渠道价格，新增 `channel_ids`，移除 `channel_overrides_may_apply`；`/v1/models` 同样只列所选渠道的模型。模型广场与请求日志显示每个渠道的实际单价和倍率。
- 移除上游成本核算：渠道“上游成本”表（`model_pricing`）、成本倍率（`cost_multiplier`）、系统设置里的分时规则（`time_pricing`）、请求日志与日汇总的 `upstream_cost`。模型售价的“计费倍率”（`multiplier`）移除。
- 迁移 24：模型售价的倍率先乘进各项单价再删列，客户价不变；所有渠道倍率为 1、无固定价，所有 Key 不绑定渠道，升级后计费与选路与之前一致。旧的渠道成本设置不会转成客户价。升级前未结算的记录仍可正常结算。降级恢复列结构，但渠道倍率、固定价和 Key 渠道绑定会丢失，上游成本不可恢复。
- 模型检测的“最近检测记录”改为分页表格，每页 10 条，可按健康、降智筛选；检测明细和错误收进展开行。`GET /api/models/probes` 新增 `kind`、`page`、`size`（最大 50）参数并返回 `total`，默认每页 10 条，原来固定返回最近 20 条。
- 售价查找改为对外模型名优先：映射出来的名字（如 `gpt-4o-lite → gpt-4o`）在“模型售价”里有自己的价格时按它计费，没有时仍用上游模型名的价格。之前上游名有价格时会盖过别名价格。请求报价、`/v1/me` 和模型广场同步生效。
- 渠道编辑弹窗重新排版：分为连接信息、模型、路由、上游成本四块，上游成本默认折叠并注明只影响成本统计、不影响客户售价；模型映射和成本改为带表头、可直接修改的行，P/C/R/W/Q 缩写换成中文列名，空行或重复模型在保存前提示。
- 吞吐优化：渠道列表进程内缓存 2 秒（修改、删除渠道时立即失效），结算预占靠唯一约束判重、结算时复用已知归属，每个推理请求的 SQL 从 29 条降到 26 条；MySQL 连接池上限可用 `MYSQL_POOL_SIZE` 配置，上游 HTTP 连接池上限提高到 1000。本机基准约 120 请求/秒，提升约 10%。

### 交付与升级

- 迁移 18–22 保留 Key 与历史费用，旧自定义账号进入停用租户；旧 roles 不再参与运行授权。
- JWT 与上游加密密钥分离、主密钥外置。升级需先应用迁移并执行 app.migrate_secrets；旧 JWT 重新登录。
- Python 依赖合并为一个 `backend/requirements.txt`，全部固定版本，含测试库；删除 requirements.in/.lock、requirements-dev.in/.lock，playwright、pip-audit 改为按需安装。Dockerfile 的 pip 走阿里云镜像、npm 走 npmmirror，删除未使用的 `backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`。新增 `./service.sh deploy` 一条命令部署，Compose 镜像名改为本地构建的 `five-api:latest`。
- 前端依赖锁定并修复已知生产依赖漏洞；镜像固定基础摘要、非 root 运行。补齐真实 MySQL/Redis、HTTP/SDK、恢复与浏览器检查。
- 提供运维升级、贡献、兼容矩阵和可复现轻量 HTTP 基准；移除 Nginx HTTPS 示例，反向代理与证书由部署方自行处理。
- 网关容器改为无状态：Compose 不再挂载 `gateway_secrets` 卷，也不读取 `.env`，数据库密码等直接写在文件里。SECRET_KEY、ENCRYPTION_KEY 可选：不填时 JWT 每次启动随机（重启需重新登录），上游 Key 用内置公开密钥加密；之后改用自有密钥执行 `python -m app.migrate_secrets --from-default` 重新加密。删除 `./service.sh secrets`。旧部署升级前须先从卷中导出密钥并填入 Compose，见运维文档。网关端口改为对外开放 `8080`，直连时 Key IP 白名单按真实来源 IP 判断。
- README 改为产品介绍：说明用途、与 new-api 和 LiteLLM 的差异、选型建议和使用边界，按 0.4.0 界面重新截图；开发计划与测试命令移出首页。删除 `push.sh` 和 `SECURITY.md`，安全处置以运维文档为准。
- 测试新增全路由鉴权矩阵、推理 Key 拒绝路径、计费不变量、渠道熔断与 SQL 预算护栏；删除未引用的计费上限函数，清理测试警告。删除已被真实 HTTP 冒烟脚本取代的 `tests/smoke` 及其 `smoke` 标记。
- 支持多 worker：镜像入口改为 `docker-entrypoint.sh`，默认按 CPU 核数（最多 8）启动 `uvicorn --workers`，Compose 填 `WORKERS` 可改。worker 在 Redis 写心跳，崩溃后其他 worker 接管它的预占（未发往上游的释放，已发往上游的标为未知结果继续占用，迟到用量仍按实际结算）；结算恢复、额度重置、日志清理、模型巡检和渠道探测按周期在 Redis 认领，只由一个 worker 执行；模型巡检状态改存 Redis；`/metrics` 汇总全部 worker。MySQL 连接池默认改为每个 worker `200 / WORKERS`（10–50），Compose 中的 MySQL 设为 `max_connections=500`，外部 MySQL 需相应调大。所有 worker 共享 SECRET_KEY，不填时每次容器启动生成一个。计费规则不变。
- 压测分模拟与真实两部分：`scripts.benchmark` 自行启动多 worker 网关、用模拟上游测处理上限，8 核机器每分钟约 2.6 万次，单个租户约 9000 次；新增 `scripts.real_benchmark`，用真实渠道以正常业务并发（默认 10/20/50，最高 200）对比直连与经过网关，并逐条核对扣费，DeepSeek 实测首字只慢约 20 毫秒以内。两个脚本默认只打印结果，`--output` 才写文件。
- 文档合并：`docs/PERMISSIONS_DESIGN.md`、`docs/MANAGEMENT_API.md` 和开发计划中的产品范围合并为 `docs/DESIGN.md`；删除已全部完成的 `docs/DEVELOPMENT_PLAN.md`，历史记录见本文件与 git。压测结果单独整理为 `docs/BENCHMARK.md`（模拟环境与真实 DeepSeek 渠道），原始数据为 `docs/benchmarks/real-deepseek.json` 与 `synthetic.json`。
- 商用部署按多 worker 验收；小规模降智题仅供参考，不能证明真实型号。CLI/桌面客户端未在本次验收中认证。

## [0.3.0] - 2026-10-18

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
- 视频：`/v1/videos` 按 OpenAI 视频接口透传，支持创建（含参考图上传）、查询、下载、删除和 remix。提交成功时按秒数乘按次价计费，查询和下载固定走创建它的渠道和上游 Key，只有创建它的 Key 能访问。内置价格新增 `sora-2`、`sora-2-pro`。

### 变更

- MySQL 和 Redis 端口只绑 `127.0.0.1`。镜像只信任本机发来的 `X-Forwarded-For`。
- 镜像构建固定走国内源（pip 用阿里云，npm 用 npmmirror），去掉 `PIP_INDEX_URL`、`NPM_REGISTRY` 构建参数。
- 流式请求中途断开或上游没给用量时，按已转发的内容估算 token 计费，不再记 0。
- 改密码、管理员被改密码或停用后，旧的登录凭证立即失效。
- 同一 IP 或用户名 15 分钟内登录失败 10 次，暂停登录 15 分钟。
- 统计接口改读按天汇总表，不再扫描整张请求日志。
- 删掉 Anthropic 和 OpenAI 之间的格式转换代码。请求本来就只发给同协议渠道，这部分已经不会被调用。
- 修复客户端中途断开流式请求时不计费、不写日志、并发名额一直被占的问题。
- 修复全新数据库上迁移失败、容器起不来的问题。
- 上游 5xx、超时和非 JSON 报错统一返回 502，报错信息不再带上游地址。完整报错仍在日志里。
- 剩余额度不够本次预估时仍然放行，只在已用和预留占满总额后拒绝。原来剩余额度少的 Key 会因预估偏大被提前拒绝。
- 请求里内嵌的 base64 图片、音频和文件，每个按 1600 token 预估。原来按字符数估，一张 1 MB 的图会估成 33 万 token，预留过多额度，设了每分钟 token 上限的 Key 会被误拒。
- 识别 Codex 的 `session-id` 请求头，Codex 会话能按会话统计花费并固定渠道。
- 按天汇总改用 MySQL 8.0.19 起的行别名写法，不再每个请求刷一条弃用警告。
- 概览页的渠道费用占比不再显示费用为 0 的 `unknown`（网关直接拒绝的请求）。
- 上游返回 HTTP 200 但正文只有 `error` 时按上游报错处理：日志记为失败，服务端错误切换到下一个渠道，报错原样返回客户端。New API 等中转常这样返回。`invalid_request_error`、`authentication_error` 等客户端错误保留对应 4xx，不触发切换和熔断。

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
