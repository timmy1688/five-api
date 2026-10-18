# Five API

[中文](README.md) · [Changelog](CHANGELOG.md)

[![CI](https://github.com/timmy1688/five-api/actions/workflows/ci.yml/badge.svg)](https://github.com/timmy1688/five-api/actions/workflows/ci.yml)

A self-hosted AI gateway for a team. Upstream keys stay in the gateway. Each person gets a key with its own USD quota, model list, and rate limit. Claude Code and the OpenAI SDK only change the base URL.

## Why this one

**Claude Code works, with tools and thinking intact.** `/v1/messages` is forwarded as-is to an Anthropic channel. `tool_use`, `thinking`, streaming, and vendor beta fields stay. OpenAI requests are forwarded as-is to an OpenAI-compatible channel. The same model can have one channel for each client.

```bash
export ANTHROPIC_BASE_URL=http://your-server
export ANTHROPIC_API_KEY=sk-your-gateway-key
```

**You can match what each person spent to the vendor bill.** Quota is USD on the key. One request has four prices: input, cache read, cache write, and output. Claude cache writes are 1.25× input. Other models bill writes at the input price. The gateway reserves an estimate when the request starts and settles the real usage when it finishes. If a stream is cut off or the upstream reports no usage, the gateway estimates it from what it forwarded. A key can join a team. The team has its own USD budget, and every key in it spends from that budget. A key can limit requests per minute and tokens per minute.

**Several keys per channel, several fallbacks per model.** Put one upstream key per line. A key that gets a 429 cools down for the upstream `retry-after`. A 401 or 403 cools it down for 10 minutes. The other keys keep serving, and one session stays on one key so its cache keeps hitting. When every channel for a model fails, the fallback chain in Settings moves to the next model, for example `claude-opus-4-7 → claude-sonnet-4-6`.

**Limits per 5 hours, per day, per week.** Besides the total quota, keys and teams can cap USD spend over the last 5 hours, 24 hours, and 7 days. Going over returns `window_limit` or `team_window_limit`. Near the cap, rules can swap an expensive model for a cheaper one, and the `x-five-downgraded-to` header names the model used. A spent budget still rejects.

**See what the cache saves.** Cost insights charts the daily cache hit rate and the money saved, split by model, key, and channel, and lists the most expensive sessions. A session comes from a request header, the Claude Code session id, or a fingerprint of the conversation start. With auto cache on, Anthropic requests without `cache_control` get cache marks on tools, the system prompt, and the last message.

**Reconcile with the vendor bill line by line.** Upload the vendor's CSV export on the Reconciliation page. Date, cost, and model columns are detected, and each day and model is compared with gateway billing, with rows over or under flagged. The log detail lists every price bucket with usage, unit price, price source, and cache savings. Time-of-day pricing multiplies the cost inside chosen hours, matching off-peak discounts or peak surcharges.

**Alerts reach your team chat.** Budget thresholds, channel circuit open and recovery, and a high per-minute share of 5xx go to Feishu, DingTalk, WeCom, or any JSON webhook. Feishu and DingTalk signing is supported, and URLs and secrets are stored encrypted. The Get started page has configs for Claude Code, Codex, Cursor, and the SDKs, ready to copy once you paste a key.

**Security checks do not stop the call. Review one person when you need to.** Keywords look only at the outgoing request. Secret patterns check the request and the reply for private keys, AWS access keys, GitHub tokens, and Slack tokens. The log stores the pattern name, not the secret. After a hit, the request and the reply both continue. Quota, model permission, and rate limits are what reject a call.

Inference audit stores the request only for keys that have audit on. Replies are not saved. AI review does not run after every request. Open the Audit page and it reviews that key’s saved requests one by one. Each review sends the first 400 characters of the system prompt and the last 1,200 characters of the latest user message. Earlier turns, images, and replies stay out, so more requests do not make a single review longer. The same excerpt is not sent again for 10 minutes. When the review finishes, you can generate and download a report. A script key can turn audit off: no marks, no review, and no stored request. On the Security page, turn secret patterns on, keep keywords to internal names, and point AI audit at a cheap OpenAI-compatible model.

| | Five API | A typical gateway |
|---|---|---|
| Claude Code | The request arrives unchanged, with tools and thinking | Converted into another format, then forwarded |
| Billing | Per person. Cache writes follow the vendor price, and quota is reserved before the call | Totals only, so parallel calls can overspend |
| Security | A hit is only logged. Each saved request is reviewed alone, as a short excerpt | A hit stops the request |
| Failure | Same-protocol failover, key rotation with cooldowns inside a channel, a circuit breaker, then a model fallback chain | Often tries a channel that speaks another protocol |
| Cost | Cache hit rate and savings per session, CSV bill reconciliation, downgrade near the budget | Totals only |
| Code | About 15,000 lines, Python and Vue 3, 21 permissions | Often tens of thousands of lines |

## Screenshots

The admin UI and the API are the same process.

![Dashboard](docs/images/dashboard.png)

![Channels](docs/images/channels.png)

![API Keys](docs/images/api-keys.png)

![Request Logs](docs/images/logs.png)

![Audit](docs/images/audit.png)

![Security](docs/images/security.png)

![Model Pricing](docs/images/model-prices.png)

## Production

Install Docker, then from the project directory:

```bash
docker compose up -d
```

No `.env` file is required. Compose pulls `ghcr.io/timmy1688/five-api` when a release exists and builds from source otherwise. The admin UI and the API share one port, host port 80 by default. Open `http://your-server`. The first login is `admin` / `admin123`, and the UI asks for a new password before anything else. The database, Redis, and the signing key live in `./data`. `docker compose down` leaves that directory in place.

MySQL and Redis publish their ports on `127.0.0.1` only, so other machines cannot reach them. The gateway talks to them over the container network. The gateway trusts `X-Forwarded-For` only from the local machine.

The gateway waits for MySQL and Redis before it runs migrations. `/healthz` reports both, and the Docker health check uses it. `/metrics` answers only inside the container by default. To scrape it from Prometheus, set `METRICS_TOKEN` in `docker-compose.yml` and send `Authorization: Bearer <token>`.

To change the published port or a password, edit the values in `docker-compose.yml`, then run `docker compose up -d` again. `INIT_ADMIN_PASSWORD` applies only when the admin account is created. Changing a password signs out every earlier session. Ten failed logins from one IP or for one username within 15 minutes pause logins for 15 minutes.

```bash
docker compose up -d --build   # rebuild after changing the source; pip and npm use mirrors in China
docker compose logs -f gateway
docker compose down
```

After an upgrade, click Sync latest prices on Model Pricing once. Changes per version are in [CHANGELOG.md](CHANGELOG.md).

## Development

You need Python 3.11+, Node.js 20+, and Docker. Compose still starts MySQL and Redis with the defaults above. No `.env` file is required.

```bash
./service.sh install
./service.sh start
```

The frontend is at `http://localhost:5001` and the backend at `http://localhost:5002`. The dev server forwards `/api` and `/v1` to the backend.

```bash
./service.sh stop
./service.sh logs
```

The database account matches the values in `docker-compose.yml`. To change a password, change it in that file and put the same values in a `.env` file for the local backend.

## Connect

`provider` is the wire protocol. `openai` covers OpenAI, Gemini, Qwen, vLLM, and compatible relays. `anthropic` covers Claude, or DeepSeek’s Anthropic endpoint (`https://api.deepseek.com/anthropic`).

Copy `sk-xxx` when the key is created; it is shown once. Sync the built-in prices on Model Pricing. A channel price of 0 makes that tier free.

Fields the client left out stay out, so the upstream applies its own defaults. Upstream rate-limit headers (`x-ratelimit-*`, `anthropic-ratelimit-*`, `retry-after`, `request-id`) come back unchanged, so SDK backoff keeps working. The upstream `x-request-id` is renamed `x-upstream-request-id`; the gateway's own `X-Request-ID` is for log lookup. `/v1/messages/count_tokens`, which Claude Code calls, goes to an Anthropic channel and is not billed. When the upstream lacks it, the gateway returns a local estimate.

| Endpoint | Channel | Billing |
|---|---|---|
| `/v1/chat/completions` `/v1/completions` `/v1/embeddings` | openai | tokens |
| `/v1/responses` (streaming too) | openai | tokens, from `response.completed` when streaming |
| `/v1/messages` | anthropic | tokens |
| `/v1/images/generations` `/v1/images/edits` `/v1/images/variations` | openai | per-request price for each image, plus tokens when the upstream reports them |
| `/v1/audio/speech` | openai | input characters at the input price (enter the per-million-character price), plus the per-request price |
| `/v1/audio/transcriptions` `/v1/audio/translations` | openai | per-request price, plus tokens when the upstream reports them |
| `/v1/rerank` | openai | tokens the upstream reports, plus the per-request price |

Enter per-request prices on Model Pricing, or in column Q of a channel's pricing.

```python
from openai import OpenAI
client = OpenAI(api_key="sk-your-gateway-key", base_url="http://your-server/v1")
client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "Hello"}])
```

```
fresh = prompt - cache_read - cache_write
cost  = (fresh × input + cache_read × cache_read_price + cache_write × cache_write_price + completion × output) / 1_000_000
```

Channel price wins, then the global price. A channel row without a write price uses that channel's input price. An explicit 0 makes writes free. Quota is reserved up front and settled from the real usage. Sync default prices once so Claude write prices become 1.25× input.

## Rest

```bash
cd backend && ../.venv/bin/pytest -m smoke && ../.venv/bin/pytest -m regression
```

Optional environment variables are in [.env.example](.env.example). Architecture is in [CLAUDE.md](CLAUDE.md). [MIT License](LICENSE). Cost is an estimate and can differ from the upstream invoice. The full statement is in [DISCLAIMER.md](DISCLAIMER.md) (Chinese).
