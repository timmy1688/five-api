<div align="center">

# Five API

**给别人分 AI 额度、每一笔都算清楚的自托管网关**

开户、分额度、租户自管 Key，Claude Code 和 Codex 直接接入。一条命令部署，MIT 许可，没有企业版。

<strong>简体中文</strong> | <a href="docs/README.en.md">English</a>

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/timmy1688/five-api?color=brightgreen)](https://github.com/timmy1688/five-api/releases/latest)
[![License](https://img.shields.io/github/license/timmy1688/five-api?color=brightgreen)](LICENSE)
[![Image](https://img.shields.io/badge/image-ghcr.io-blue)](https://github.com/timmy1688/five-api/pkgs/container/five-api)

[快速开始](#quick-start) · [接入客户端](docs/CLIENTS.md) · [运维与升级](docs/OPERATIONS.md) · [压测报告](docs/BENCHMARK.md) · [路线图](ROADMAP.md) · [更新记录](CHANGELOG.md)

![Five API 控制台](docs/images/dashboard.png)

</div>

---

## Five API 是什么

Five API 是一个多租户 AI 网关。你接入 OpenAI、Claude、Gemini、DeepSeek、通义千问等上游，给每个租户开户、分配美元额度；租户自己创建 Key，只能花自己的额度，每一次调用都按实际服务的渠道精确记账。

- **对外转售**：租户是你的客户。足额预占不超卖，缺价不放行，逐笔可对账。
- **企业内部**：租户是部门、团队或项目。部门预算与成本分摊、限流、请求审计与泄密排查。

## 为什么选 Five API

- **每一笔都对得上**：先足额预占再调上游，扣费和日志同一事务提交。真实 DeepSeek 渠道 320 笔流式请求逐笔重算，**0 笔不一致**。
- **几乎不增加延迟**：真实渠道下首字只比直连慢 **6–19 毫秒**；8 核机器每分钟可处理约 **2.6 万次**请求。
- **Claude Code、Codex 实测可用**：改一个地址就能让团队的编码 Agent 走你的额度和审计。
- **企业功能全部开源**：租户自管 Key、IP 白名单、请求审计、AI 泄密审查都在 MIT 版本里，`./service.sh deploy` 一条命令起来。

<a id="quick-start"></a>

## 快速开始

```bash
git clone https://github.com/timmy1688/five-api.git && cd five-api
./service.sh deploy   # 拉取 ghcr.io/timmy1688/five-api，启动网关、MySQL、Redis
```

打开 `http://服务器IP:8080`，用 `admin` / `admin123` 登录（首次登录强制改密码）。添加渠道、配置模型售价、给租户开户，租户创建 Key 后：

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer sk-..." -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","max_tokens":64,"messages":[{"role":"user","content":"Hello"}]}'
```

OpenAI SDK 把 `base_url` 改成 `http://服务器IP:8080/v1`，Anthropic SDK 改成 `http://服务器IP:8080`，其余代码不用动。

## 功能

<details open>
<summary><b>精确计费</b> - 先占住钱再放行，每一笔都能对上</summary>

<br>

- **先足额预占，再调上游**：按输入加最大输出估算费用，在 MySQL 行锁事务里连同所有在途请求核对 Key 和租户余额，够才放行。多进程、多 Key 并发打同一个租户，也不会一起越过余额；记账不可用时直接拒绝，不先放行后补账。
- **没配价格不放行**：模型没配售价时拒绝请求，不按 0 记账；只有显式填 0 才免费。
- **价格在请求前锁定**：中途调价不影响已发出的请求。
- **扣费、日志同一事务**：Key 扣费、租户扣费、请求日志、日用量要么都写入，要么都不写；记账失败后台恢复且只恢复一次，上游结果未知的请求继续占着额度等人工核对。
- **断流也计费**：客户端中途断开按已转发内容计费；上游没返回用量时按内容估算并标明来源。
- **四档计价**：输入、缓存读、缓存写、输出分别计价，图片、语音、视频可按次计价。

实际用量超出预估时照实扣费、不会少收，余额可能出现一次请求范围内的小额负数（例如没设 `max_tokens` 却输出超过 4096 token）。每条保证都有自动化测试，CI 每次提交都跑：

| 保证 | 测试 |
| --- | --- |
| 用量在预估内时，预占覆盖每一笔扣费；多进程共享余额不超卖 | `test_end_to_end_charge_never_exceeds_the_reservation`、`test_two_workers_never_overspend_a_shared_tenant_budget` |
| 缺价不放行、不按 0 计 | `test_unpriced_model_does_not_reach_upstream`、`test_selling_quote_never_silently_prices_at_zero` |
| 价格锁定 | `test_selling_price_is_snapshotted_before_the_upstream_call` |
| 记账失败恰好恢复一次，结果未知继续占额度 | `test_accounting_rolls_back_and_recovers_exactly_once`、`test_timeout_keeps_unknown_work_occupied` |
| 断流计费、不重放上游 | `test_real_http_stream_and_client_cancellation_releases_leases`、`test_disconnect_after_first_byte_does_not_replay_upstream` |

```bash
cd backend && ../.venv/bin/pytest -q tests/test_billing_invariants.py tests/test_billing_reliability.py
```

设计细节见 [为什么我们的计费不会漏钱](docs/articles/why-billing-does-not-leak.md)。

![成本洞察](docs/images/insights.png)

</details>

<details>
<summary><b>租户与 Key</b> - 平台开户分额度，租户自己管 Key</summary>

<br>

- 平台管理员和租户两种固定角色；租户只能管理自己的 Key，所有查询在服务端校验归属。
- 租户和 Key 两层额度、RPM、TPM、并发限制，以及 5 小时、1 天、7 天滚动限额，额度可按月自动重置；租户下所有 Key 共享租户额度。
- Key 可设 IP 白名单、可用模型、可用渠道、过期时间；明文只显示一次，撤销后保留用量记录。
- 平台可以给自己创建自用 Key，自动归入内部空间，和客户账目分开。

![租户账号](docs/images/tenants.png)

</details>

<details>
<summary><b>按渠道定价与路由</b> - 同一模型不同渠道不同价，故障自动绕开</summary>

<br>

- 每个渠道按模型售价乘以价格倍率，或给单个模型设固定价；按实际服务的渠道计费。
- Key 可以限定渠道，只在所选渠道间选路和切换，按候选中最贵的报价预占。
- 优先级分层，同层按权重、最少在途或最低延迟选路；多 Key 号池、粘性会话、模型回退链。
- 5xx、超时、429、上游 Key 失效自动切换渠道，流式在首包前切换；连续失败自动熔断；图片、视频等不幂等请求不重复提交。

![渠道](docs/images/channels.png)

</details>

<details>
<summary><b>请求审计与泄密排查</b> - 谁发了什么，一键让 AI 逐条审查</summary>

<br>

- 按 Key 保存请求内容（不保存回复），自动扫描私钥、AWS、GitHub、Slack 等密钥，不阻断调用。
- 员工离职或怀疑泄密时，在审计页选中 Key，让便宜模型逐条审查最近的请求，生成可下载的审计报告；审过的不重复送审。

![审计报告](docs/images/audit.png)

</details>

<details>
<summary><b>模型质量</b> - 健康检测与降智参考</summary>

<br>

- 定时健康检测，默认每 15 分钟；模型广场展示实际计费价、渠道和健康状态。
- 每天用合成题检查 GPT/Claude 渠道的指令遵循、推理和工具调用，留存历史作为降智信号。它只是回归信号，不能证明上游真实型号。

![模型广场](docs/images/models.png)

</details>

<details>
<summary><b>接入 Claude Code、Codex</b> - 改一个地址，编码 Agent 走你的额度</summary>

<br>

Claude Code（实测 2.1.197，需要 Anthropic 协议渠道），写入 `~/.claude/settings.json`：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash"
  }
}
```

Codex（实测 0.164.0，上游需支持 Responses），写入 `~/.codex/config.toml` 后 `export FIVE_API_KEY=sk-...`：

```toml
model = "deepseek-v4-flash"
model_provider = "five"

[model_providers.five]
name = "Five API"
base_url = "https://your-gateway/v1"
env_key = "FIVE_API_KEY"
wire_api = "responses"
```

Cursor 需要公网 HTTPS 网关，尚未实测。完整说明和常见问题见 [接入教程](docs/CLIENTS.md)。

</details>

<details>
<summary><b>省钱与安全</b> - 缓存洞察、自动降级、密钥隔离</summary>

<br>

- 成本洞察按天看缓存命中和节省金额；Anthropic 请求可自动加缓存标记；额度接近上限时自动降级到便宜模型。
- 上游 Key 加密存储，可配置自有加密密钥，与登录密钥分离且不入库。
- 控制台支持中文和英文。

</details>

### 支持的上游与接口

原生透传，不做协议互转，用量口径与上游一致。

| 渠道协议 | 常见上游 | 网关接口 |
| --- | --- | --- |
| OpenAI 兼容 | OpenAI、Gemini、DeepSeek、通义千问，以及 vLLM 等自部署服务 | `/v1/chat/completions`、`/v1/responses`、`/v1/embeddings`、`/v1/images/*`、`/v1/audio/*`、`/v1/rerank`、`/v1/videos` |
| Anthropic | Anthropic、DeepSeek 等提供 Anthropic 协议的上游 | `/v1/messages`、`/v1/messages/count_tokens` |

`GET /v1/models` 只返回这个 Key 能用的模型。已实测的 SDK 和客户端版本见 [兼容矩阵](docs/COMPATIBILITY.md)。

## 和 new-api、LiteLLM 对比

| | Five API | [new-api](https://github.com/QuantumNous/new-api) | [LiteLLM](https://github.com/BerriAI/litellm) |
|---|---|---|---|
| 定位 | 平台开户，按客户或部门分账 | 公开中转站，自助注册、在线充值 | 企业内部出口，100+ 供应商 |
| 预扣费 | 输入加输出上限足额预占，MySQL 事务核对 | 只预扣估算输入；余额超 10 美元跳过预扣 | 依赖 Redis，硬上限需另开 fail-closed |
| 未配置价格 | 拒绝请求 | 返回价格错误 | 放行，按 0 记账 |
| 请求内容审计 | 按 Key 保存，密钥扫描，AI 审查出报告 | 日志不保存请求内容，管理员查看提问的需求标为[无计划](https://github.com/QuantumNous/new-api/issues/7609) | 可开启保存 prompt；密钥检测属[企业版](https://docs.litellm.ai/docs/enterprise) |
| 租户自管 Key、IP 白名单 | MIT 版本包含 | 支持 | 团队管理员、IP 白名单属企业版 |
| 模型质量检测 | 健康检测 + 降智参考检测 | 连通性和响应时间 | 连通性 |

对比依据 2026 年 10 月的公开文档和 Issue。new-api 的预扣行为见 `trust_quota_usd`，成本核算见 [#4933](https://github.com/QuantumNous/new-api/issues/4933)；LiteLLM 预算见[文档](https://docs.litellm.ai/docs/proxy/users)，缺价按 0 记账见[文档](https://docs.litellm.ai/docs/proxy/cost_tracking)。

**适合选别的情况**：需要自助注册、在线支付、兑换码，选 new-api；需要 Bedrock、Vertex 等大量供应商或协议互转，选 LiteLLM；需要多台机器高可用或 SSO，Five API 目前不支持。

## 性能

一台 8 核 16 GB 机器，每轮都逐笔核对扣费：

| 测试 | 结果 |
|---|---|
| 模拟环境处理上限 | 多个租户合计每分钟约 2.6 万次（8 个进程）；单个租户约 9000 次 |
| 真实 DeepSeek，同时 10–50 个流式请求 | 全部成功，首字只比直连慢 6–19 毫秒 |

单个租户的请求要经过同一行锁，这是余额精确的代价。测试条件、原始数据和重跑命令见 [压测报告](docs/BENCHMARK.md)。

## 部署与运维

配置都直接写在 `docker-compose.yml` 里，改完重新执行 `./service.sh deploy`：

| 配置 | 用途 |
| --- | --- |
| `MYSQL_PASSWORD` 等数据库密码 | 上线前必须改，gateway 和 mysql 两处要一致 |
| `INIT_ADMIN_USERNAME`、`INIT_ADMIN_PASSWORD` | 只在还没有管理员时创建首个账号 |
| `SECRET_KEY` | 登录令牌密钥；不填时每次重启登录失效 |
| `ENCRYPTION_KEY` | 上游 Key 的加密密钥；不填时用内置公开密钥加密，已有渠道后再设置须先迁移 |
| `WORKERS` | 进程数，默认按 CPU 核数，最多 8 |
| `ports` | 默认对外 8080 |

<details>
<summary><b>正式上线前</b></summary>

<br>

- 前面加 HTTPS 反向代理，关闭响应缓冲、读取超时不低于 600 秒，并把代理地址写入 `FORWARDED_ALLOW_IPS`，否则 IP 白名单可被伪造来源绕过。
- 数据库和加密密钥分开备份。配置了自有 `ENCRYPTION_KEY` 时，只有数据库备份解不开渠道 Key。
- 升级时把 `docker-compose.yml` 里的镜像版本号改成新版本再部署；**从旧版本升级先看 [运维文档](docs/OPERATIONS.md)**，可能需要迁移。国内拉取 ghcr.io 慢时可本地构建同名镜像，方法见运维文档。

</details>

## 使用边界

- 没有在线支付、自助注册、SSO、组织层级和自定义角色。
- Claude Code、Codex 只实测了上面列出的版本；Cursor 未实测。
- 降智检测只是回归信号；定时检测的上游费用由平台承担。
- 计费以上游返回的用量为准，可能与厂商账单口径不同；请同时在上游账户设置预算告警。

## 参与贡献

后端 FastAPI、Tortoise ORM，前端 Vue 3、Element Plus；需要 Python 3.12、Node.js 20.19+，开发时只有 MySQL、Redis 跑在容器里：

```bash
./service.sh install   # 安装依赖，默认国内源
./service.sh start     # 后端 :5002，前端 :5001
cd backend && ../.venv/bin/pytest -q
```

| 目录 | 职责 |
| --- | --- |
| `backend/app/routers/` | 管理 API 与 OpenAI、Anthropic 推理入口 |
| `backend/app/services/` | 计费、预占结算、路由、限流、审计 |
| `backend/app/providers/` | 上游适配 |
| `backend/tests/` | 快测与连真实 MySQL、Redis 的集成测试 |
| `frontend/src/` | 管理控制台 |

新贡献者可以从 [good first issue](https://github.com/timmy1688/five-api/labels/good%20first%20issue) 或 [路线图](ROADMAP.md) 里的任务开始，测试环境与约定见 [贡献指南](CONTRIBUTING.md)。

## 社区与支持

| 资源 | 入口 |
| --- | --- |
| 文档 | [接入客户端](docs/CLIENTS.md) · [运维与升级](docs/OPERATIONS.md) · [设计说明](docs/DESIGN.md) · [兼容矩阵](docs/COMPATIBILITY.md) · [压测报告](docs/BENCHMARK.md) |
| 使用问题与想法 | [Discussions](https://github.com/timmy1688/five-api/discussions) |
| 缺陷与功能建议 | [GitHub Issues](https://github.com/timmy1688/five-api/issues)，请附上版本、部署方式、复现步骤和脱敏日志 |
| 安全问题 | 不要公开提交 Issue，也不要附带密钥、提示词或数据库内容；先开一个不含敏感信息的 Issue 申请私下沟通 |

觉得有用的话，点个 Star 让更多人看到。

## 免责声明

> [!WARNING]
> - 本项目仅供合法授权的 AI 接口管理、组织内部额度分配、用量统计与成本核算等场景使用，禁止用于任何违反法律法规或上游服务条款的用途。
> - 使用者须合法取得上游 API Key、账号和接口权限，并自行遵守上游服务条款。因违反上游条款导致的封号、扣费或其他损失，由使用者自行承担。
> - 对外提供生成式 AI 服务或转售 API 时，使用者须自行完成所在地要求的备案、许可、内容安全、实名、日志留存、税务和上游授权等合规义务，例如[《生成式人工智能服务管理暂行办法》](http://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)。
> - 请求审计会保存请求内容。在组织内部使用前，应告知员工并遵守个人信息保护等相关法律；对外服务时须依法处理客户数据。
> - 计费、用量、降智检测等数据仅供参考，可能与上游厂商的账单和实际型号不一致，不构成财务、法律或合规意见。请以厂商账单为准，并在上游账户设置预算告警。
> - 本软件按 MIT 许可「按原样」提供，不附带任何明示或暗示的担保。作者和贡献者不对使用本软件造成的任何直接或间接损失承担责任，包括但不限于资金损失、数据丢失、服务中断和第三方索赔。
> - 本项目与 OpenAI、Anthropic、Google、DeepSeek、阿里云等厂商无关联，文中提到的产品名称和商标归各自所有者所有。
>
> 使用本项目即表示你已阅读并同意以上内容。

## 许可证

[MIT](LICENSE)，可商用。
