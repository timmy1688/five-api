# Five API

[中文](../README.md) · [Operations](OPERATIONS.md) · [Compatibility](COMPATIBILITY.md) · [Contributing](../CONTRIBUTING.md)

A lightweight, MIT-licensed AI gateway for self-hosted commercial deployments. It forwards OpenAI and Anthropic wire protocols and includes a Vue console.

Platform administrators provision tenant accounts and budgets. Each tenant has one account and manages its own inference keys. Administrators can create platform-use keys, separately from customer tenants. Management uses short-lived JWTs; inference uses hashed API keys. There is no dynamic RBAC, member hierarchy or online payment flow.

Budgets are shared across tenant keys. Requests reserve sufficient estimated cost before dispatch; actual usage, tenant/key debits, request logs and daily totals commit in one MySQL transaction. Durable records support idempotent recovery and explicit review of uncertain upstream outcomes. This does not guarantee exactly-once upstream execution or zero overspend.

The Model Hub shows effective selling prices, channel availability and probe history. Availability checks default to every 15 minutes. GPT/Claude degradation reference checks default to every 24 hours and evaluate instruction following, reasoning and tool use. These synthetic checks cannot authenticate model identity and incur platform upstream costs.

Customer price multipliers and channel discounts are independent. Catalog imports only add missing rows and preserve existing prices, multipliers and status. The bundled catalog is a versioned reference, not live vendor pricing.

## Development

Use Python 3.12, Node.js 20.19+ and MySQL 8/Redis 7:

```bash
./service.sh install
./service.sh start
```

Vite runs on localhost:5001 and Uvicorn on localhost:5002. Only MySQL/Redis use containers during development. Dependency downloads default to Aliyun and npmmirror.

## Single-machine deployment

```bash
docker compose up -d --build
```

The non-root image serves the API and UI on localhost:8080. Terminate public HTTPS with your existing Nginx using [the example](../deploy/nginx.conf). Configure production passwords and keep encryption/JWT secrets outside the database in a separately protected file or environment.

Default first-install credentials are admin/admin123, with a mandatory password change. They do not reset existing accounts. Read the operations guide before upgrading: migrations and external-secret migration are required.

## Using the gateway

An OpenAI SDK uses `https://your-domain/v1`; an Anthropic SDK uses the gateway root. Tenants log in, change their temporary password and create a key shown only once. See the compatibility matrix for tested SDK versions, endpoints and unverified desktop/CLI clients.

Run `cd backend && ../.venv/bin/pytest -q` for the fast suite. Real-service tests are opt-in and restricted to a disposable database. See the contribution guide for setup, browser checks, dependency locks and the reproducible HTTP benchmark.
