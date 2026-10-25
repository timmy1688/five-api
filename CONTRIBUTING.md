# Contributing

Keep changes focused on the lightweight product scope in [the plan](docs/DEVELOPMENT_PLAN.md). Use Python 3.12, Node.js 20.19+ (CI: 24), MySQL 8 and Redis 7.

## Local setup

Run `./service.sh install` and `./service.sh start`. The frontend is localhost:5001, backend localhost:5002. Existing development databases may contain useful work; smoke scripts remove only resources they create.

Python runtime dependencies are in backend/requirements.in and requirements.lock. Development/test tools use requirements-dev.in and requirements-dev.lock. Install with `pip install --require-hashes -r requirements-dev.lock`. Downloads may use `-i https://mirrors.aliyun.com/pypi/simple` or Tsinghua. Frontend installs use `npm ci --registry=https://registry.npmmirror.com`.

## Validation

```bash
cd backend
../.venv/bin/pytest -q
../.venv/bin/python scripts/release_check.py
```

Integration tests require a pre-created disposable database matching five_api_test_*; never use the application database. Grant your test user access only to that test database.

```bash
FIVE_TEST_MYSQL_DB=five_api_test_ci \
FIVE_TEST_REDIS_URL=redis://127.0.0.1:6379/15 \
FIVE_TEST_MYSQL_CONTAINER=five-api-mysql-1 \
../.venv/bin/pytest -q tests/integration
```

Tests create/drop tables inside that database. Redis uses DB 15 with a unique namespace, removed at teardown. FIVE_TEST_MYSQL_CONTAINER enables the mysqldump/restore test and must name the corresponding MySQL container. CI provisions its own disposable services.

For browser checks install a matching Chromium with Playwright, or set PLAYWRIGHT_CHROMIUM_EXECUTABLE to an existing executable. Run `../.venv/bin/python -m scripts.smoke_tenants --ui` against the local development services. It exercises platform and tenant flows, self-use keys, health/capability probes and scoped settings saves. No real vendor credentials are needed for those smoke requests.

Frontend: `cd frontend && npm run build`. Audit with `npm audit --omit=dev --registry=https://registry.npmjs.org`; npmmirror does not provide the audit API. Python: `pip-audit --disable-pip --no-deps -r requirements.lock`.

## Dependencies and migrations

Regenerate both locks with the pinned uv version from the development lock:

```bash
uv pip compile --generate-hashes --no-header --no-annotate --universal --python-version 3.12 -o requirements.lock requirements.in
uv pip compile --generate-hashes --no-header --no-annotate --universal --python-version 3.12 -o requirements-dev.lock requirements-dev.in
```

Set UV_DEFAULT_INDEX to the Aliyun or Tsinghua mirror when needed. Review dependency changes and audit before merging. Runtime and development pins must match; the release check verifies this.

Generate migrations using Aerich after changing ORM models. Keep historical migrations versioned, inspect SQL and test fresh installation plus legacy upgrades against MySQL. Do not replace a data migration with generate_schemas on an existing database.

Preserve tenant scope on every query and separate management credentials from inference keys. Use internal UUIDs for accounting and store immutable quotations. Keep global role checks on the backend, and never log raw credentials.

## Benchmarks and releases

`python -m scripts.benchmark --requests 200 --concurrency 10` measures a local synthetic upstream directly and through the running gateway. Results include conditions and are not vendor/model performance claims.

A release requires passing CI, a matching version/tag, changelog and upgrade notes. Tag publishing builds amd64/arm64 images only after quality checks. Maintainers create release tags; ordinary pushes do not publish a release.

Describe the concrete behavior, validation and migration impact in PRs. Report security issues through [SECURITY.md](SECURITY.md), with secrets removed.
