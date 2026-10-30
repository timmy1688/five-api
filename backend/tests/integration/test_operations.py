"""Destructive checks are restricted by the integration fixture to five_api_test_*."""
import asyncio
import json
import os
import shutil
import socket
import ssl
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from tortoise import connections

from app.config import settings
from app.models import APIKey, Channel, ModelPrice, RequestLog, Tenant, UsageDaily, User
from app.services.billing_quotes import quote_cost, selling_quote
from app.utils.secrets import create_external, decrypt_secret, encrypt_secret, load_secret_key
from tests.integration.conftest import serve

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]


async def clear_tables():
    db = connections.get("default")
    tables = await db.execute_query_dict("SHOW TABLES")
    names = [str(next(iter(row.values()))).replace("`", "``") for row in tables]
    await db.execute_script("SET FOREIGN_KEY_CHECKS=0;" +
                            "".join(f"DROP TABLE `{name}`;" for name in names) +
                            "SET FOREIGN_KEY_CHECKS=1;")


async def migrate(config=None):
    env = {**os.environ, "MYSQL_DATABASE": os.environ["FIVE_TEST_MYSQL_DB"]}
    args = [str(Path(sys.executable).with_name("aerich"))]
    if config:
        args.extend(["-c", str(config)])
    process = await asyncio.create_subprocess_exec(*args, "upgrade", cwd=ROOT, env=env,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
    assert process.returncode == 0, output.decode()


async def insert_legacy(table, **values):
    db = connections.get("default")
    columns = await db.execute_query_dict(f"SHOW COLUMNS FROM `{table}`")
    row = {}
    for column in columns:
        name, kind = column["Field"], column["Type"].lower()
        if name in values:
            row[name] = values[name]
        elif "auto_increment" in column["Extra"] or column["Null"] == "YES" or column["Default"] is not None:
            continue
        elif "int" in kind or "decimal" in kind or "float" in kind:
            row[name] = 0
        elif kind == "json":
            row[name] = "{}"
        elif "date" in kind:
            row[name] = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            row[name] = ""
    names = ",".join(f"`{name}`" for name in row)
    await db.execute_query(f"INSERT INTO `{table}` ({names}) VALUES ({','.join(['%s'] * len(row))})", list(row.values()))


async def test_fresh_database_runs_every_aerich_migration():
    await clear_tables()
    await migrate()
    db = connections.get("default")
    versions = await db.execute_query_dict("SELECT version FROM aerich ORDER BY id")
    files = sorted(Path(__file__).parents[2].glob("migrations/models/[0-9]*_*.py"),
                   key=lambda path: int(path.name.split("_")[0]))
    assert [row["version"] for row in versions] == [path.name for path in files]
    assert versions[-1]["version"].startswith("24_")
    tenant = await Tenant.create(name="fresh", quota_total=0)
    assert tenant.rpm_limit == 120 and tenant.tpm_limit == 100000 and tenant.concurrent_limit == 10
    await migrate()  # repeated startup is harmless
    assert await Tenant.filter(id=tenant.id).exists()


async def migrate_until(tmp_path, last: int):
    legacy_dir = tmp_path / "migrations" / "models"
    legacy_dir.mkdir(parents=True)
    for path in (ROOT / "migrations" / "models").glob("*.py"):
        if int(path.name.split("_", 1)[0]) <= last:
            shutil.copyfile(path, legacy_dir / path.name)
    config = tmp_path / "aerich.toml"
    config.write_text('[tool.aerich]\ntortoise_orm="app.config.TORTOISE_ORM"\nlocation=' +
                      json.dumps(str(legacy_dir.parent)) + '\nsrc_folder="."\n')
    await migrate(config)


async def test_channel_pricing_upgrade_keeps_every_charge_and_drops_upstream_costs(tmp_path):
    await clear_tables()
    await migrate_until(tmp_path, 23)
    await insert_legacy("model_prices", model="half", prompt_price=Decimal("3"), completion_price=Decimal("15"),
                        cached_price=Decimal("0.3"), cache_write_price=Decimal("3.75"), request_price=Decimal("0.04"),
                        multiplier=Decimal("0.5"), currency="USD", is_active=1)
    await insert_legacy("model_prices", model="odd", prompt_price=Decimal("0.123457"), completion_price=Decimal("1"),
                        multiplier=Decimal("1.3333"), currency="USD", is_active=1)
    await insert_legacy("channels", name="discounted", provider="openai", base_url="https://x.example.com",
                        models='["half"]', model_mapping="{}", model_pricing='{"half": {"prompt": 1, "completion": 2}}',
                        cost_multiplier=Decimal("0.6"))
    tenant = await Tenant.create(name="pricing-upgrade", quota_total=-1)
    await insert_legacy("api_keys", name="k", key_hash="c" * 64, key_prefix="sk-k", tenant_id=tenant.id,
                        quota_total=-1, allowed_models="[]", allowed_ips="[]", is_enabled=1)
    await migrate()
    half = await ModelPrice.get(model="half")
    assert (half.prompt_price, half.completion_price, half.cached_price, half.cache_write_price, half.request_price) == (
        Decimal("1.5"), Decimal("7.5"), Decimal("0.15"), Decimal("1.875"), Decimal("0.02"))
    assert (await ModelPrice.get(model="odd")).prompt_price == Decimal("0.164605")
    channel = await Channel.get(name="discounted")
    # Upstream cost settings must never turn into customer prices.
    assert channel.price_multiplier == 1 and channel.price_overrides == {}
    assert (await APIKey.get(name="k")).channel_ids == []
    quote = await selling_quote("half", channel=channel)
    assert quote_cost(quote, 1_000_000, 1_000_000, 0, 0, 0)["cost"] == Decimal("9")


async def test_legacy_upgrade_preserves_bills_and_does_not_promote_custom_roles(tmp_path):
    await clear_tables()
    await migrate_until(tmp_path, 17)
    await insert_legacy("roles", id=1, name="Super Admin", permissions="[]", is_builtin=1)
    await insert_legacy("roles", id=2, name="Custom", permissions='["user:write","role:write"]')
    await insert_legacy("admins", id=1, username="legacy-admin", role_id=1, is_active=1)
    await insert_legacy("admins", id=2, username="legacy-custom", role_id=2, is_active=0)
    await insert_legacy("teams", id=7, name="old-team", quota_total=10, quota_used=Decimal("0.250000"), is_enabled=1)
    await insert_legacy("api_keys", id=1, name="old-key", key_hash="a"*64, key_prefix="old", team_id=7,
                        quota_total=5, quota_used=Decimal("0.250000"), allowed_models="[]", allowed_ips="[]",
                        is_enabled=1)
    await insert_legacy("api_keys", id=2, name="unassigned", key_hash="b"*64, key_prefix="old",
                        quota_total=5, quota_used=Decimal("0.125000"), allowed_models="[]", allowed_ips="[]",
                        is_enabled=1)
    await insert_legacy("request_logs", request_id="legacy-request", api_key_id=1,
                        model_requested="gpt-4o", cost=Decimal("0.250000"))
    await insert_legacy("usage_daily", day=datetime.now().date(), api_key_id=1, team_id=7,
                        model="gpt-4o", cost=Decimal("0.250000"))
    await migrate()
    assert (await User.get(id=1)).role == "platform_admin"
    custom = await User.get(id=2)
    assert custom.role == "tenant" and custom.is_active and custom.must_change_password
    assert not (await Tenant.get(id=custom.tenant_id)).is_enabled
    old = await Tenant.get(id=7)
    assert old.quota_used == Decimal("0.25") and old.rpm_limit == old.tpm_limit == old.concurrent_limit == -1
    other = await Tenant.get(name="__legacy_unassigned__")
    assert other.quota_used == Decimal("0.125") and (await APIKey.get(id=2)).tenant_id == other.id
    log = await RequestLog.get()
    assert log.tenant_id == 7 and log.cost == Decimal("0.25") and log.usage_source == "legacy"
    assert (await UsageDaily.get()).tenant_id == 7


async def test_sql_dump_restore_preserves_history_and_requires_external_key(tmp_path, monkeypatch):
    container = os.environ.get("FIVE_TEST_MYSQL_CONTAINER")
    if not container:
        pytest.skip("Set FIVE_TEST_MYSQL_CONTAINER for the mysqldump recovery check")
    monkeypatch.setattr(settings, "SECRETS_FILE", str(tmp_path / "secrets.json"))
    pair = create_external(settings.SECRET_KEY, settings.ENCRYPTION_KEY)
    tenant = await Tenant.create(name="restore", quota_total=10, quota_used=Decimal("1.25"))
    ch = await Channel.create(name="restore", provider="openai", base_url="https://api.openai.com",
                              api_key=encrypt_secret("restore-only-upstream-secret"), models=["gpt-4o"])
    env = {**os.environ, "MYSQL_PWD": settings.MYSQL_PASSWORD}
    process = await asyncio.create_subprocess_exec(
        "docker", "exec", "-e", "MYSQL_PWD", container, "mysqldump",
        "--user=" + settings.MYSQL_USER, "--no-tablespaces", "--single-transaction",
        "--skip-lock-tables", os.environ["FIVE_TEST_MYSQL_DB"], env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    dump, error = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, error.decode()
    assert b"restore-only-upstream-secret" not in dump
    assert pair["encryption_key"].encode() not in dump and pair["jwt_secret"].encode() not in dump
    await clear_tables()
    await connections.get("default").execute_script(dump.decode())
    monkeypatch.setattr(settings, "SECRET_KEY", "")
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    await load_secret_key()
    assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("1.25")
    assert decrypt_secret((await Channel.get(id=ch.id)).api_key) == "restore-only-upstream-secret"


async def test_https_checks_certificate_and_refuses_untrusted_peer(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from ipaddress import ip_address
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(days=1)).add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ip_address("127.0.0.1"))]), False)
            .sign(key, hashes.SHA256()))
    keyfile, certfile = tmp_path / "key.pem", tmp_path / "cert.pem"
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    app = FastAPI()
    @app.get("/probe")
    async def probe():
        return {"ok": True}
    async with serve(app, ssl_keyfile=str(keyfile), ssl_certfile=str(certfile)) as base:
        async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=str(certfile)), trust_env=False) as client:
            assert (await client.get(base + "/probe")).json() == {"ok": True}
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(base + "/probe")


async def test_sigterm_drains_app_and_closes_connections(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    env = {**os.environ, "MYSQL_DATABASE": os.environ["FIVE_TEST_MYSQL_DB"],
           "REDIS_URL": os.environ["FIVE_TEST_REDIS_URL"], "SECRETS_FILE": str(tmp_path / "secrets.json")}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
        "--no-access-log", "--log-level", "info", "--timeout-graceful-shutdown", "5", cwd=ROOT, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    output = b""
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
            for _ in range(100):
                if process.returncode is not None:
                    break
                try:
                    if (await client.get(f"http://127.0.0.1:{port}/healthz")).status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("Gateway never became ready")
        assert process.returncode is None
        process.terminate()
        output, _ = await asyncio.wait_for(process.communicate(), timeout=12)
        # Uvicorn restores and re-raises SIGTERM after its graceful shutdown.
        assert process.returncode in (0, -15), output.decode()
        assert b"Application shutdown complete" in output
        assert b"Task was destroyed" not in output and b"Shutdown recovery incomplete" not in output
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
