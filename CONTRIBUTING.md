# Contributing

Keep changes focused on the lightweight product scope in [the design doc](docs/DESIGN.md). Use Python 3.12, Node.js 20.19+ (CI: 24), MySQL 8 and Redis 7.

## Local setup

Run `./service.sh install` and `./service.sh start`. The frontend is localhost:5001, backend localhost:5002. Existing development databases may contain useful work; smoke scripts remove only resources they create.

All Python dependencies, including test libraries, are pinned in backend/requirements.txt. Install with `pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt`. Browser checks additionally need `pip install playwright`. Frontend installs use `npm ci --registry=https://registry.npmmirror.com`.

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

Frontend: `cd frontend && npm run build`. Audit with `npm audit --omit=dev --registry=https://registry.npmjs.org`; npmmirror does not provide the audit API. Python: `pip install pip-audit && pip-audit --disable-pip --no-deps -r requirements.txt`.

## Dependencies and migrations

Edit backend/requirements.txt directly and keep every line pinned with `==`, including transitive packages under "Transitive pins". After an upgrade, reinstall into a clean virtual environment, run the tests and pip-audit, and review the diff. The release check rejects unpinned lines or extra requirements files.

Generate migrations using Aerich after changing ORM models. Keep historical migrations versioned, inspect SQL and test fresh installation plus legacy upgrades against MySQL. Do not replace a data migration with generate_schemas on an existing database.

Preserve tenant scope on every query and separate management credentials from inference keys. Use internal UUIDs for accounting and store immutable quotations. Keep global role checks on the backend, and never log raw credentials.

## Benchmarks and releases

`python -m scripts.real_benchmark --channel <id> --model <model>` steps up streaming concurrency against a real channel, directly and through a multi-worker gateway, and recomputes every charge; it spends a small amount on the upstream. `python -m scripts.benchmark --workers 1,2,4,8` measures gateway capacity with a synthetic upstream. Both create and remove their own tenants and keys; pass `--output` to save the JSON report, and record results in docs/COMPATIBILITY.md.

A release requires passing CI, a matching version/tag, changelog and upgrade notes. Tag publishing builds amd64/arm64 images only after quality checks. Maintainers create release tags; ordinary pushes do not publish a release.

Describe the concrete behavior, validation and migration impact in PRs. Do not report security issues publicly; open a non-sensitive issue to request a private channel, with secrets removed.
