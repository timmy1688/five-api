<div align="center">

# Five API

**A self-hosted AI gateway for handing out AI budgets to others and accounting for every charge**

<a href="../README.md">简体中文</a> | <strong>English</strong>

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/timmy1688/five-api?color=brightgreen)](https://github.com/timmy1688/five-api/releases/latest)
[![License](https://img.shields.io/github/license/timmy1688/five-api?color=brightgreen)](../LICENSE)
[![Image](https://img.shields.io/badge/image-ghcr.io-blue)](https://github.com/timmy1688/five-api/pkgs/container/five-api)

[Clients](CLIENTS.md) · [Operations](OPERATIONS.md) · [Compatibility](COMPATIBILITY.md) · [Benchmarks](BENCHMARK.md) · [Roadmap](../ROADMAP.md) · [Changelog](../CHANGELOG.md) (linked documents are in Chinese)

</div>

---

## About

Five API connects OpenAI, Claude, Gemini, DeepSeek, Qwen and other upstreams. The platform opens an account for each tenant with a USD budget; tenants manage their own keys, can spend only their own budget, and every charge is accounted for. MIT licensed with no enterprise edition, deployed with `./service.sh deploy`.

| Use case | Tenants are | Mainly used |
| --- | --- | --- |
| Reselling | Your customers | Full reservation without overselling, no unpriced requests, per-channel prices, per-request reconciliation |
| Inside a company | Departments, teams or projects | Department budgets and chargeback, rate limits, request audit and leak investigation, degradation checks |

It is not a public relay: there is no self sign-up or online top-up, and accounts are opened by the platform. Nor does it aim to support the most providers; getting the money right comes first.

![Dashboard](images/dashboard.png)

## Why the money does not leak

Whether you bill customers or charge back departments, the costly failures are budgets overspent, calls never billed and calls billed twice. Five API reserves the money first and only then lets the request through:

- **Reserve in full before calling the upstream.** The cost of the input plus the maximum output is checked against the key and tenant balance, together with every in-flight request, inside a MySQL row-locked transaction. Concurrent requests from several workers and keys cannot jointly spend past a balance. If accounting is unavailable the request is refused, never let through to be billed later.
- **No price, no request.** A model without a selling price is rejected instead of billed at zero. Only an explicit zero price makes it free.
- **The price is fixed before dispatch**, so changing prices mid-request does not affect it.
- **Charges and logs commit together.** Key debit, tenant debit, request log and daily usage commit in one transaction. Failed accounting is recovered exactly once; requests with an unknown upstream outcome keep their reservation until reviewed.
- **Disconnected streams are billed** for what was forwarded. Missing upstream usage is estimated from the content, and the log records the usage source.

Usage above the estimate is still charged in full, never under-billed, so a balance can go slightly negative by at most one request, for example when a request sets no `max_tokens` and the reply exceeds the 4096-token default. Have clients set `max_tokens` for a hard cap.

<details>
<summary><b>Verify it yourself</b>: each guarantee has automated tests that CI runs on every push</summary>

| Guarantee | Tests |
| --- | --- |
| Within the estimate, the reservation covers every charge; workers sharing a budget never oversell it | `test_end_to_end_charge_never_exceeds_the_reservation`, `test_two_workers_never_overspend_a_shared_tenant_budget` |
| Unpriced models are refused, never billed at zero | `test_unpriced_model_does_not_reach_upstream`, `test_selling_quote_never_silently_prices_at_zero` |
| Prices are fixed before dispatch | `test_selling_price_is_snapshotted_before_the_upstream_call` |
| Failed accounting recovers exactly once; unknown outcomes stay reserved | `test_accounting_rolls_back_and_recovers_exactly_once`, `test_timeout_keeps_unknown_work_occupied` |
| Broken streams are billed and never replayed upstream | `test_real_http_stream_and_client_cancellation_releases_leases`, `test_disconnect_after_first_byte_does_not_replay_upstream` |

```bash
cd backend && ../.venv/bin/pytest -q tests/test_billing_invariants.py tests/test_billing_reliability.py
```

The benchmarks recompute every charge from the logged tokens and the price and reconcile it with the charge, key usage and tenant usage. All 8 simulated rounds pass, and 320 requests through a real DeepSeek channel show 0 mismatches. Raw data and commands are in the [benchmark report](BENCHMARK.md).

</details>

## Compared with new-api and LiteLLM

| | Five API | [new-api](https://github.com/QuantumNous/new-api) | [LiteLLM](https://github.com/BerriAI/litellm) |
|---|---|---|---|
| Focus | Provisioned accounts, billing per customer or department | Public relay with self sign-up and online top-up | Internal enterprise egress, 100+ providers |
| Reservation | Input plus output cap reserved in full, checked in a MySQL transaction | Only estimated input reserved; skipped when the balance exceeds 10 USD | Relies on Redis; hard limits need fail-closed enabled separately |
| Unpriced model | Request refused | Price error returned | Allowed and billed at 0 |
| Request audit | Saved per key, secret scanning, AI review report | Request content not stored; viewing prompts is [not planned](https://github.com/QuantumNous/new-api/issues/7609) | Prompt logging optional; secret detection is [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Tenant-managed keys, IP allowlists | Included under MIT | Supported | Team admins and IP allowlists are enterprise |
| Model quality checks | Health checks plus degradation reference checks | Connectivity and latency | Connectivity |

Based on public documentation and issues as of October 2026. For new-api's reservation see `trust_quota_usd`; for LiteLLM budgets see the [docs](https://docs.litellm.ai/docs/proxy/users) and zero-cost billing of unpriced models in [cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking).

**When to choose something else**: for self sign-up, online payment or redeem codes, use new-api. For Bedrock, Vertex and many other providers or protocol translation, use LiteLLM. Multi-machine high availability and SSO are not supported by Five API yet.

## Capabilities

| Area | What it does |
| --- | --- |
| Billing | Input, cache read, cache write and output priced separately; images, audio and video per call. Each channel can price the same model differently (selling price × channel multiplier, or a fixed price), billed at the channel that served the request |
| Tenants | Two fixed roles, platform administrator and tenant. Tenants manage their own keys, IP allowlists, RPM/TPM/concurrency and budgets; every query is scoped on the server |
| Routing | Priority tiers, then weight, least in-flight or lowest latency; multi-key pools, sticky sessions, model fallback chains; keys can be bound to chosen channels |
| Failover | 5xx, timeouts, 429 and revoked upstream keys switch channels; streams switch only before the first byte; circuit breaker; non-idempotent requests such as images and videos are never resubmitted |
| Audit | Request excerpts saved per key and scanned for private keys and AWS, GitHub and Slack tokens; a cheap model can review a key's requests and produce a downloadable report |
| Model quality | Periodic health checks, plus a daily synthetic suite for GPT/Claude channels covering instruction following, reasoning and tool use |
| Cost | Daily cache hit and savings insights; automatic Anthropic cache markers; automatic downgrade to a cheaper model near the budget |
| Security | Upstream keys encrypted at rest with an optional master key kept apart from the JWT key and outside the database; API keys shown once |
| Console | Vue 3, Chinese and English |

### Endpoints

Requests pass through natively without protocol translation, so usage matches the upstream.

| Type | Endpoints |
| --- | --- |
| OpenAI Chat / Responses | `POST /v1/chat/completions`, `POST /v1/responses` |
| Anthropic Messages | `POST /v1/messages`, `POST /v1/messages/count_tokens` |
| Embeddings / rerank | `POST /v1/embeddings`, `POST /v1/rerank` |
| Images / audio | `/v1/images/*`, `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/audio/translations` |
| Video | `/v1/videos` create, query, download, delete, remix; tasks isolated per tenant |
| Models | `GET /v1/models`, returning only the models this key can use |

## Screenshots

| Cost insights | Model hub |
|---|---|
| ![Cost insights](images/insights.png) | ![Model hub](images/models.png) |
| **Channels** | **Tenants** |
| ![Channels](images/channels.png) | ![Tenants](images/tenants.png) |
| **Request logs** | **Audit report** |
| ![Request logs](images/logs.png) | ![Audit](images/audit.png) |

## Quick start

### Deploy

Requires Docker and Docker Compose; the image supports amd64 and arm64:

```bash
git clone https://github.com/timmy1688/five-api.git && cd five-api
./service.sh deploy   # pulls ghcr.io/timmy1688/five-api and starts the gateway, MySQL and Redis
```

Open `http://SERVER_IP:8080` and sign in as `admin` / `admin123`; a password change is required on first login. Switch the console to English with the 中文 / EN toggle on the login page or in the header.

### First request

1. Add an upstream under Channels with its key and models, then test it.
2. Set a price under Selling Prices. Models without a price are refused.
3. Open a tenant under Tenant accounts with a budget. The tenant signs in and creates a key under API Keys; it is shown once.
4. Point clients at the gateway: `http://SERVER_IP:8080/v1` for OpenAI protocol, `http://SERVER_IP:8080` for Anthropic protocol.

List the models the key can use, then send a request:

```bash
export FIVE_API_KEY=sk-...
curl http://localhost:8080/v1/models -H "Authorization: Bearer $FIVE_API_KEY"
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $FIVE_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","max_tokens":64,"messages":[{"role":"user","content":"Hello"}]}'
```

### Claude Code and Codex

**Claude Code** (tested with 2.1.197) needs an Anthropic-protocol channel. In `~/.claude/settings.json`, using the gateway root without `/v1`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://ai.example.com",
    "ANTHROPIC_AUTH_TOKEN": "sk-...",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash"
  }
}
```

**Codex CLI** (tested with 0.164.0) only speaks the Responses API, so the channel's upstream must support `/v1/responses`. In `~/.codex/config.toml`, then `export FIVE_API_KEY=sk-...`:

```toml
model = "deepseek-v4-flash"
model_provider = "five"

[model_providers.five]
name = "Five API"
base_url = "https://ai.example.com/v1"
env_key = "FIVE_API_KEY"
wire_api = "responses"
```

**Cursor** calls a custom base URL from Cursor's servers, so the gateway needs a public HTTPS address; it has not been tested end to end. See the [client guide](CLIENTS.md) for troubleshooting.

## Deployment and operations

All settings are written directly in `docker-compose.yml`; run `./service.sh deploy` again after changing them:

| Setting | Purpose |
| --- | --- |
| `MYSQL_PASSWORD` and other database passwords | Change before production; keep gateway and mysql in sync |
| `INIT_ADMIN_USERNAME`, `INIT_ADMIN_PASSWORD` | Create the first administrator only when none exists |
| `SECRET_KEY` | Login token key; without it logins end on every restart |
| `ENCRYPTION_KEY` | Upstream key encryption; without it a built-in public key is used. Migrate before setting it once channels exist |
| `WORKERS` | Worker processes, default one per CPU core, up to 8 |
| `ports` | 8080 by default |

For production:

- Put an HTTPS reverse proxy in front with response buffering off and a read timeout of at least 600 seconds, and list the proxy in `FORWARDED_ALLOW_IPS`; otherwise forged source addresses can bypass IP allowlists.
- Back up the database and the encryption key separately. With your own `ENCRYPTION_KEY`, a database backup alone cannot decrypt channel keys.
- To upgrade, change the image version in `docker-compose.yml` and deploy again; **read the [operations guide](OPERATIONS.md) before upgrading from an older release**, since migrations may be required.

## Performance

On one 8-core, 16 GB machine, with every charge reconciled in each run:

| Test | Result |
|---|---|
| Simulated upstream capacity | About 26,000 requests per minute across many tenants (8 workers); about 9,000 for a single tenant |
| Real DeepSeek channel, 10–50 concurrent streams | All succeeded; first token only 6–19 ms slower than calling DeepSeek directly |

A single tenant's requests pass through one row lock, the price of an exact balance. Full data is in the [benchmark report](BENCHMARK.md).

## Limits

- No online payment, SSO, organization hierarchy or custom roles.
- Claude Code and Codex are tested only at the versions listed above; Cursor is untested.
- Degradation checks are regression signals and cannot prove which model an upstream serves; their upstream cost is paid by the platform.
- Billing follows the usage reported by the upstream, which may differ from the vendor's invoice. Also set budget alerts in your upstream accounts.

## Development

Backend FastAPI and Tortoise ORM, frontend Vue 3 and Element Plus. Requires Python 3.12 and Node.js 20.19+; only MySQL and Redis run in containers during development:

```bash
./service.sh install   # dependencies, Aliyun and npmmirror mirrors by default
./service.sh start     # backend :5002, frontend :5001
cd backend && ../.venv/bin/pytest -q
```

| Directory | Responsibility |
| --- | --- |
| `backend/app/routers/` | Management API and OpenAI/Anthropic inference endpoints |
| `backend/app/services/` | Billing, reservation and settlement, routing, rate limits, audit |
| `backend/app/providers/` | Upstream adapters |
| `backend/tests/` | Fast tests and integration tests against real MySQL and Redis |
| `backend/scripts/` | Benchmarks, release checks, smoke tests |
| `frontend/src/` | Admin console |

See the [contribution guide](../CONTRIBUTING.md) for test setup, dependencies and migrations.

## Docs and community

| Resource | Link |
| --- | --- |
| Docs (Chinese) | [Clients](CLIENTS.md) · [Operations](OPERATIONS.md) · [Design](DESIGN.md) · [Compatibility](COMPATIBILITY.md) · [Benchmarks](BENCHMARK.md) |
| Plans | [Roadmap](../ROADMAP.md) · [Changelog](../CHANGELOG.md) |
| Questions and ideas | [Discussions](https://github.com/timmy1688/five-api/discussions) |
| Bugs and feature requests | [GitHub Issues](https://github.com/timmy1688/five-api/issues); newcomers can start with [good first issue](https://github.com/timmy1688/five-api/labels/good%20first%20issue) |
| Security | Do not open public issues or attach keys, prompts or database contents; open a non-sensitive issue to request a private channel |

Include the version, deployment method, reproduction steps and redacted logs when reporting problems.

## Disclaimer

> [!WARNING]
> - This project is intended only for lawfully authorized AI API management, internal budget allocation, usage tracking and cost accounting. Do not use it for anything that violates laws, regulations or upstream terms of service.
> - You must obtain upstream API keys, accounts and access lawfully and follow the upstream terms of service. You bear any account suspension, charges or other losses caused by violating them.
> - If you offer generative AI services or resell APIs to the public, you are responsible for the registration, licensing, content safety, identity verification, log retention, tax and upstream authorization duties required where you operate.
> - Request audit stores request content. Inform employees and comply with personal data protection laws before using it inside an organization, and handle customer data lawfully when serving others.
> - Billing, usage and degradation-check data are for reference only. They may differ from vendor invoices and the models actually served, and are not financial, legal or compliance advice. Rely on vendor invoices and set budget alerts in your upstream accounts.
> - The software is provided "as is" under the MIT License, without warranty of any kind. The authors and contributors are not liable for any direct or indirect loss arising from its use, including but not limited to financial loss, data loss, service interruption and third-party claims.
> - This project is not affiliated with OpenAI, Anthropic, Google, DeepSeek, Alibaba Cloud or any other vendor. Product names and trademarks belong to their respective owners.
>
> By using this project you confirm that you have read and agree to the above.

## License

[MIT](../LICENSE), free for commercial use.
