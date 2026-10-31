# Five API

[English](docs/README.en.md) · [接入 Claude Code/Codex/Cursor](docs/CLIENTS.md) · [运维与升级](docs/OPERATIONS.md) · [兼容矩阵](docs/COMPATIBILITY.md) · [压测报告](docs/BENCHMARK.md) · [路线图](ROADMAP.md) · [更新记录](CHANGELOG.md)

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)

**给客户转售 AI 接口、需要按客户精确分账的团队用的自托管网关。**

接入 OpenAI、Claude、Gemini、DeepSeek、通义千问等上游，给每个客户开户、分配美元额度，客户只能花自己的钱，每一笔都能对上。MIT 许可，可商用，`./service.sh deploy` 一条命令部署。

![概览](docs/images/dashboard.png)

## 钱为什么不会漏

转售最怕的不是慢，而是客户用超了、漏记了、记重了。Five API 在每个环节都选择「先占住钱再放行」：

- **先足额预占，再调上游**：按输入加最大输出估算费用，在 MySQL 行锁事务里连同所有在途请求一起核对 Key 和租户余额，够才放行。多个进程、多个 Key 并发打同一个租户，也不会一起越过余额。记账服务不可用时直接拒绝，不会先放行后补账。
- **没配价格不放行**：模型没配售价时拒绝请求，不按 0 记账；只有显式填 0 才免费。
- **价格在请求前锁定**：发出请求前记下当时的售价，请求中途调价不影响这一笔。
- **扣费、日志一起提交**：Key 扣费、租户扣费、请求日志、日用量在同一个事务里，要么都成功，要么都不写。记账失败后台恢复且只恢复一次；上游结果未知的请求继续占着额度，等人工核对，不会悄悄放掉。
- **断流也计费**：客户端中途断开，按已经转发的内容计费；上游没返回用量时按内容估算，并在日志里标明用量来源。

实际用量超出预估时照实扣费，不会少收，余额可能出现一次请求范围内的小额负数，例如没设 `max_tokens` 却输出超过 4096 token。要把上限卡死，让客户端设置 `max_tokens`。

### 自己验证

每一条都有对应的自动化测试，CI 每次提交都跑：

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

压测时会逐笔重算：用日志里的 token 数乘以售价，和实际扣费、Key 已用、租户已用三处对账。模拟环境 8 轮对账全部通过，真实 DeepSeek 渠道 320 笔请求 0 笔不一致，原始数据和重跑命令见 [压测报告](docs/BENCHMARK.md)。

## 和 new-api、LiteLLM 对比

| | Five API | [new-api](https://github.com/QuantumNous/new-api) | [LiteLLM](https://github.com/BerriAI/litellm) |
|---|---|---|---|
| 定位 | 平台开户、按客户分账 | 公开中转站，自助注册、在线充值 | 企业内部出口，100+ 供应商 |
| 预扣费 | 输入加输出上限足额预占，MySQL 事务核对 | 只预扣估算输入；余额超 10 美元跳过预扣 | 依赖 Redis，硬上限需另开 fail-closed |
| 未配置价格 | 拒绝请求 | 返回价格错误 | 放行，按 0 记账 |
| 请求内容审计 | 按 Key 保存，密钥扫描，AI 审查出报告 | 日志不保存请求内容，管理员查看提问的需求标为[无计划](https://github.com/QuantumNous/new-api/issues/7609) | 可开启保存 prompt；密钥检测属[企业版](https://docs.litellm.ai/docs/enterprise) |
| 租户自管 Key、IP 白名单 | MIT 版本包含 | 支持 | 团队管理员、IP 白名单属企业版 |
| 模型质量检测 | 健康检测 + 降智参考检测 | 连通性和响应时间 | 连通性 |

对比依据 2026 年 10 月的公开文档和 Issue。new-api 的预扣行为见 `trust_quota_usd`，成本核算见 [#4933](https://github.com/QuantumNous/new-api/issues/4933)；LiteLLM 预算见[文档](https://docs.litellm.ai/docs/proxy/users)，缺价按 0 记账见[文档](https://docs.litellm.ai/docs/proxy/cost_tracking)。

**适合选别的情况**：需要自助注册、在线支付、兑换码，选 new-api；需要 Bedrock、Vertex 等大量供应商或协议互转，选 LiteLLM；需要多副本高可用或 SSO，Five API 目前不支持。

## 功能一览

- **同一模型，渠道不同价**：每个渠道按模型售价乘以价格倍率，也可以给单个模型设固定价；客户在 Key 上选择渠道，只在所选渠道间切换，按实际服务的渠道计费。
- **调用可审计，泄密可追查**：按 Key 保存请求内容，自动扫描私钥、AWS、GitHub、Slack 等密钥；员工离职或怀疑泄密时，一键让便宜模型逐条审查这个 Key 最近的请求，生成可下载的审计报告；审过的不重复送审。
- **上游掉线、Key 失效自动绕开**：5xx、超时、429、上游 Key 失效都会切换渠道，流式请求在首包前切换；连续失败自动熔断。图片、视频等不幂等请求不会被重复提交。
- **能发现模型被降智**：定时健康检测，另外每天用合成题检查 GPT/Claude 渠道的指令遵循、推理和工具调用，留存历史作为退化信号。
- **企业功能全部开源**：租户自管 Key、IP 白名单、内容审计、AI 审查都在 MIT 版本里，没有企业版。
- **协议**：Anthropic SDK、Claude Code 走 `/v1/messages`，OpenAI SDK、Codex、Cursor 走 `/v1/*`，原生透传不互转。支持 chat、responses、embeddings、图片、语音、rerank、视频。
- **计费**：输入、缓存读、缓存写、输出四档分别计价，图片、语音、视频可按次计价。
- **租户**：平台管理员和租户两种角色；租户只能管理自己的 Key，所有查询在服务端校验归属。
- **路由**：优先级分层，同层按权重、最少在途或最低延迟选路；多 Key 号池、粘性会话、模型回退链。
- **省钱**：成本洞察按天看缓存命中和节省金额；Anthropic 请求可自动加缓存标记；额度接近上限时自动降级到便宜模型。
- **安全**：上游 Key 加密存储，可配置自有加密密钥，与 JWT 密钥分离且不入库；API Key 明文只显示一次。

## 界面

| 成本洞察 | 模型广场 |
|---|---|
| ![成本洞察](docs/images/insights.png) | ![模型广场](docs/images/models.png) |
| **渠道** | **租户账号** |
| ![渠道](docs/images/channels.png) | ![租户账号](docs/images/tenants.png) |
| **请求日志** | **审计报告** |
| ![请求日志](docs/images/logs.png) | ![审计](docs/images/audit.png) |
| **路由策略** | **接入指南** |
| ![路由策略](docs/images/settings.png) | ![接入指南](docs/images/onboarding.png) |

## 快速部署

```bash
./service.sh deploy   # 拉取发布镜像 ghcr.io/timmy1688/five-api 并启动全部容器
```

打开 `http://服务器IP:8080`，用 `admin` / `admin123` 登录，首次登录会强制改密码。上线前改掉 `docker-compose.yml` 里的数据库密码；需要重启不掉登录、上游 Key 用自有密钥加密时，按文件里的注释填 SECRET_KEY、ENCRYPTION_KEY。**从旧版本升级先看 [运维文档](docs/OPERATIONS.md)**，不能直接替换镜像。

## 接入

平台添加渠道、配置售价、开通租户；租户创建 Key 后，客户端只改地址：

```python
from openai import OpenAI

client = OpenAI(api_key="sk-your-gateway-key", base_url="https://ai.example.com/v1")
print(client.chat.completions.create(
    model="gpt-5.6", messages=[{"role": "user", "content": "Hello"}],
).choices[0].message.content)
```

Anthropic SDK 和 Claude Code 的 `base_url` 填网关根地址。Claude Code、Codex 已实测，配置见 [接入教程](docs/CLIENTS.md)；端点和已验证的 SDK 版本见 [兼容矩阵](docs/COMPATIBILITY.md)。

## 性能

一台 8 核 16 GB 机器上的压测结果，模拟环境与真实 DeepSeek 渠道都测过，每轮逐笔核对扣费全部一致：

| 测试 | 结果 |
|---|---|
| 模拟环境处理上限 | 多个租户合计每分钟约 2.6 万次（8 个进程）；单个租户约 9000 次 |
| 真实 DeepSeek，同时 10–50 个流式请求 | 全部成功，首字只比直连慢 6–19 毫秒 |

测试条件、各进程数和各并发的完整数据见 [压测报告](docs/BENCHMARK.md)。

## 使用边界

- 没有在线支付、SSO、组织层级和自定义角色。
- Claude Code、Codex 只实测了 [接入教程](docs/CLIENTS.md) 中列出的版本；Cursor 需要公网 HTTPS 网关，未实测。
- 降智检测只是回归信号，不能证明上游真实型号；定时检测的上游费用由平台承担。
- 计费以上游返回的用量为准，可能与厂商账单口径不同；请同时在上游账户设置预算告警。

本地开发和测试见 [贡献指南](CONTRIBUTING.md)。安全问题请勿公开提交 Issue，也不要附带密钥、提示词或数据库内容。
