# Five API

[中文](../README.md) · [Clients (Chinese)](CLIENTS.md) · [Operations (Chinese)](OPERATIONS.md) · [Compatibility (Chinese)](COMPATIBILITY.md) · [Benchmarks (Chinese)](BENCHMARK.md) · [Roadmap (Chinese)](../ROADMAP.md) · [Changelog](../CHANGELOG.md) · [Contributing](../CONTRIBUTING.md)

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)

**A self-hosted AI gateway for teams that resell AI APIs to their own customers and need every customer billed exactly.**

Connect OpenAI, Claude, Gemini, DeepSeek, Qwen and other upstreams, open an account for each customer with a USD budget, and let each customer spend only their own money, with every charge accounted for. MIT licensed, free for commercial use, deployed with one command.

![Dashboard](images/dashboard.png)

## Why the money does not leak

When you resell, the costly failures are customers spending past their budget, calls that are never billed, and calls billed twice. Five API reserves the money first and only then lets the request through:

- **Reserve in full before calling the upstream.** The cost of the input plus the maximum output is estimated and checked against the key and tenant balance, together with every in-flight request, inside a MySQL row-locked transaction. Concurrent requests from several workers and keys cannot jointly spend past a balance. If accounting is unavailable the request is refused; nothing is let through to be billed later.
- **No price, no request.** A model without a selling price is rejected instead of billed at zero. Only an explicit zero price makes it free.
- **The price is fixed before dispatch.** The selling price is recorded before the upstream call, so changing prices mid-request does not affect it.
- **Charges and logs commit together.** Key debit, tenant debit, request log and daily usage commit in one transaction or not at all. Failed accounting is recovered in the background exactly once. Requests with an unknown upstream outcome keep their reservation until someone reviews them.
- **Disconnected streams are billed.** If the client hangs up mid-stream, what was already forwarded is billed. When the upstream reports no usage, it is estimated from the content and the log records the usage source.

Actual usage above the estimate is still charged in full, never under-billed, so a balance can go slightly negative by at most one request, for example when a request sets no `max_tokens` and the reply exceeds the 4096-token default. Have clients set `max_tokens` for a hard cap.

### Verify it yourself

Each guarantee has automated tests that CI runs on every push:

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

## Compared with new-api and LiteLLM

| | Five API | [new-api](https://github.com/QuantumNous/new-api) | [LiteLLM](https://github.com/BerriAI/litellm) |
|---|---|---|---|
| Focus | Provisioned accounts, per-customer billing | Public relay with self sign-up and online top-up | Internal enterprise egress, 100+ providers |
| Reservation | Input plus output cap reserved in full, checked in a MySQL transaction | Only estimated input reserved; skipped when the balance exceeds 10 USD | Relies on Redis; hard limits need fail-closed enabled separately |
| Unpriced model | Request refused | Price error returned | Allowed and billed at 0 |
| Request audit | Saved per key, secret scanning, AI review report | Request content not stored; viewing prompts is [not planned](https://github.com/QuantumNous/new-api/issues/7609) | Prompt logging optional; secret detection is [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Tenant-managed keys, IP allowlists | Included under MIT | Supported | Team admins and IP allowlists are enterprise |
| Model quality checks | Health checks plus degradation reference checks | Connectivity and latency | Connectivity |

Based on public documentation and issues as of October 2026. For new-api's reservation see `trust_quota_usd`; for LiteLLM budgets see the [docs](https://docs.litellm.ai/docs/proxy/users) and zero-cost billing of unpriced models in [cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking).

**When to choose something else**: for self sign-up, online payment or redeem codes, use new-api. For Bedrock, Vertex and many other providers or protocol translation, use LiteLLM. Multi-machine high availability and SSO are not supported by Five API yet.

## Features

- **Per-channel prices for the same model.** Each channel bills the model's selling price times its price multiplier, or a fixed price per model. A key can be bound to chosen channels: failover stays inside them and each request is billed at the channel that served it.
- **Auditable calls.** Request excerpts are saved per key (never replies) and scanned for private keys and AWS, GitHub and Slack tokens without blocking calls. When someone leaves or a leak is suspected, a cheap model reviews the key's latest requests one by one and produces a downloadable report; reviewed requests are not sent again.
- **Failover.** 5xx, timeouts, 429 and revoked upstream keys switch channels; streams switch only before the first byte. Repeated failures open a circuit breaker. Non-idempotent requests such as images and videos are never resubmitted.
- **Degradation signals.** Periodic health checks, plus a daily synthetic suite for GPT/Claude channels covering instruction following, reasoning and tool use, with history kept. These checks cannot prove model identity.
- **No enterprise edition.** Tenant-managed keys, IP allowlists, content audit and AI review are all MIT.
- **Protocols.** Anthropic SDK and Claude Code use `/v1/messages`; OpenAI SDK, Codex and Cursor use `/v1/*`. Requests pass through natively without protocol translation. Chat, responses, embeddings, images, audio, rerank and video are supported.
- **Billing.** Input, cache read, cache write and output are priced separately; images, audio and video can be priced per call.
- **Tenants.** Two fixed roles, platform administrator and tenant. Tenants manage only their own keys, and every query is scoped on the server.
- **Routing.** Priority tiers, then weight, least in-flight or lowest latency; multi-key pools, sticky sessions and model fallback chains.
- **Security.** Upstream keys are encrypted at rest with an optional master key kept apart from the JWT key and outside the database. API keys are shown once.
- **Console.** Vue 3 console in Chinese and English.

## Screenshots

| Cost insights | Model hub |
|---|---|
| ![Cost insights](images/insights.png) | ![Model hub](images/models.png) |
| **Channels** | **Tenants** |
| ![Channels](images/channels.png) | ![Tenants](images/tenants.png) |
| **Request logs** | **Audit report** |
| ![Request logs](images/logs.png) | ![Audit](images/audit.png) |

## Deploy

```bash
./service.sh deploy   # pulls ghcr.io/timmy1688/five-api and starts all containers
```

Open `http://SERVER_IP:8080` and sign in as `admin` / `admin123`; a password change is required on first login. These credentials are only used when no administrator exists yet.

Before production, change the database passwords in `docker-compose.yml`. SECRET_KEY and ENCRYPTION_KEY are optional: without them logins end on restart and upstream keys are encrypted with a built-in public key. Set your own, as the comments in the file describe. To upgrade, change the image version in `docker-compose.yml` and run `./service.sh deploy` again; **read the [operations guide](OPERATIONS.md) before upgrading from an older release**, because migrations may be required.

The image supports amd64 and arm64, runs as a non-root user and starts one worker per CPU core (up to 8). Set `WORKERS` to change it.

## Connect clients

Add channels and selling prices, then create tenant accounts. Tenants sign in and create keys; clients only change the base URL.

```python
from openai import OpenAI

client = OpenAI(api_key="sk-your-gateway-key", base_url="https://ai.example.com/v1")
print(client.chat.completions.create(
    model="gpt-5.6", messages=[{"role": "user", "content": "Hello"}],
).choices[0].message.content)
```

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

**Cursor** calls a custom base URL from Cursor's servers, so the gateway needs a public HTTPS address. It has not been tested end to end. Details and troubleshooting are in the [client guide](CLIENTS.md).

## Performance

On one 8-core, 16 GB machine, with every charge reconciled in each run:

| Test | Result |
|---|---|
| Simulated upstream capacity | About 26,000 requests per minute across many tenants (8 workers); about 9,000 for a single tenant |
| Real DeepSeek channel, 10–50 concurrent streams | All succeeded; first token only 6–19 ms slower than calling DeepSeek directly |

A single tenant is capped by its row lock, which keeps its balance exact. Full data is in the [benchmark report](BENCHMARK.md).

## Limits

- No online payment, SSO, organization hierarchy or custom roles.
- Claude Code and Codex are tested only at the versions listed above; Cursor is untested.
- Degradation checks are regression signals and cannot prove which model an upstream serves; their upstream cost is paid by the platform.
- Billing follows the usage reported by the upstream, which may differ from the vendor's invoice. Also set budget alerts in your upstream accounts.

## Development

Use Python 3.12, Node.js 20.19+ and MySQL 8/Redis 7:

```bash
./service.sh install
./service.sh start
```

Vite runs on localhost:5001 and Uvicorn on localhost:5002; only MySQL and Redis run in containers during development. Dependency downloads default to Aliyun and npmmirror mirrors. Run `cd backend && ../.venv/bin/pytest -q` for the fast suite; real-service tests are opt-in and restricted to a disposable database. See the [contribution guide](../CONTRIBUTING.md) for setup, browser checks, dependencies and benchmarks.

Do not report security issues in public issues, and never attach keys, prompts or database contents.
