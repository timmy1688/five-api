"""Run from backend: ../.venv/bin/python -m scripts.smoke_tenants.

Creates uniquely named smoke resources, exercises real HTTP/MySQL/Redis, and
removes only those resources. Does not print passwords, tokens, or raw keys.
"""
import asyncio
import json
import os
import re
import secrets
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
from tortoise import Tortoise

from app.config import TORTOISE_ORM
from app.models import APIKey, Channel, ManagementEvent, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily, User, ModelProbe
from app.services.auth import hash_password

BASE = os.environ.get("FIVE_SMOKE_BASE_URL", "http://127.0.0.1:5002")


class Upstream(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        prompt = body["messages"][0]["content"]
        text = "smoke ok"
        choice = {"role": "assistant", "content": text}
        if "FIVE_" in prompt:
            nonce = re.search(r"FIVE_[a-z0-9]+", prompt).group()
            text = nonce
            if "JSON object" in prompt:
                a, b, c = map(int, re.search(r"(\d+) \* (\d+) \+ (\d+)", prompt).groups())
                text = json.dumps({"answer": a*b+c, "marker": nonce})
            choice["content"] = text
        if body.get("tools"):
            a, b, c = map(int, re.search(r"(\d+) \* (\d+) \+ (\d+)", prompt).groups())
            choice = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_smoke", "type": "function",
                "function": {"name": "report_result", "arguments": json.dumps({"answer": a*b+c})}}]}
        content = json.dumps({
            "id": "smoke-response", "object": "chat.completion",
            "choices": [{"index": 0, "message": choice}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_):
        pass


async def run():
    await Tortoise.init(config=TORTOISE_ORM)
    suffix = uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    model = "five-smoke-" + suffix
    operator = None
    tenant_ids = []
    platform_key_ids = []
    channel_id = price_id = None
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        operator = await User.create(username="smoke-admin-" + suffix, role="platform_admin",
                                     hashed_password=hash_password(password))
        async with httpx.AsyncClient(base_url=BASE, timeout=20, trust_env=False) as client:
            login = await client.post("/api/login", json={"username": operator.username, "password": password})
            assert login.status_code == 200, "platform login"
            platform = {"Authorization": "Bearer " + login.json()["access_token"]}
            tenants = []
            for label in ("a", "b"):
                username = f"smoke-{label}-{suffix}"
                created = await client.post("/api/tenants", headers=platform, json={
                    "name": username, "username": username, "password": password,
                    "quota_total": 20, "allowed_models": [model],
                })
                assert created.status_code == 201, "provision"
                tenant_ids.append(created.json()["id"])
                login = await client.post("/api/login", json={"username": username, "password": password})
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                assert (await client.get("/api/keys", headers=headers)).status_code == 403, "temporary password"
                changed = await client.put("/api/password", headers=headers, json={
                    "old_password": password, "new_password": password + "-new",
                })
                assert changed.status_code == 200, "password change"
                assert (await client.get("/api/me", headers=headers)).status_code == 401, "token revocation"
                tenants.append({"Authorization": "Bearer " + changed.json()["access_token"]})
            a, b = tenants
            key_response = await client.post("/api/keys", headers=a, json={"name": "smoke-key"})
            assert key_response.status_code == 201, "tenant key create"
            assert key_response.headers["cache-control"] == "no-store"
            key = key_response.json()
            assert (await client.get(f"/api/keys/{key['id']}", headers=b)).status_code == 404
            assert (await client.put(f"/api/keys/{key['id']}", headers=b, json={"name": "foreign"})).status_code == 404
            assert (await client.get("/api/keys", headers=b)).json()["total"] == 0
            assert (await client.post("/api/users", headers=a, json={
                "username": "forbidden", "password": password,
            })).status_code == 403
            assert (await client.put(f"/api/keys/{key['id']}", headers=a,
                                     json={"tenant_id": tenant_ids[1]})).status_code == 422
            assert (await client.get("/api/me", headers={"Authorization": "Bearer " + key["key"]})).status_code == 401

            price = await client.post("/api/model-prices", headers=platform, json={
                "model": model, "prompt_price": 1000, "completion_price": 1000,
            })
            assert price.status_code == 201
            price_id = price.json()["id"]
            channel = await client.post("/api/channels", headers=platform, json={
                "name": "smoke-channel-" + suffix, "provider": "openai",
                "base_url": f"http://127.0.0.1:{upstream.server_port}", "api_key": "",
                "models": [model, "gpt-five-smoke-" + suffix], "priority": 10000,
            })
            assert channel.status_code == 201
            channel_id = channel.json()["id"]
            if "--ui" in sys.argv:
                from scripts.tenant_ui_check import verify_ui
                await verify_ui(operator.username, password, a["Authorization"].removeprefix("Bearer "), tenant_ids, platform_key_ids,
                                model, "gpt-five-smoke-" + suffix)
            application = {"Authorization": "Bearer " + key["key"]}
            payload = {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
            response = await client.post("/v1/chat/completions", headers=application, json=payload)
            assert response.status_code == 200, "inference"
            tenant = await Tenant.get(id=tenant_ids[0])
            stored_key = await APIKey.get(id=key["id"])
            log = await RequestLog.filter(api_key_id=key["id"], status_code=200).get()
            assert tenant.quota_used == stored_key.quota_used == log.cost == Decimal("0.015"), "accounting"
            assert log.tenant_id == tenant.id
            daily = await UsageDaily.get(api_key_id=key["id"])
            assert daily.cost == log.cost and daily.tenant_id == tenant.id

            quota_body = {"quota_total": "0.015", "reason": "smoke ceiling", "operation_id": str(uuid4())}
            quota_path = f"/api/tenants/{tenant.id}/quota"
            for _ in range(2):
                assert (await client.put(quota_path, headers=platform, json=quota_body)).status_code == 200
            assert await ManagementEvent.filter(operation_id=quota_body["operation_id"]).count() == 1
            assert (await client.post("/v1/chat/completions", headers=application, json=payload)).status_code == 429
            assert (await client.put(f"/api/tenants/{tenant.id}", headers=platform,
                                     json={"is_enabled": False})).status_code == 200
            assert (await client.get("/api/keys", headers=a)).status_code == 403
            assert (await client.get("/v1/models", headers=application)).status_code == 403
            await client.put(f"/api/tenants/{tenant.id}", headers=platform, json={"is_enabled": True})
            assert (await client.delete(f"/api/keys/{key['id']}", headers=a)).status_code == 200
            replacement = await client.post("/api/keys", headers=a, json={"name": "replacement"})
            assert replacement.status_code == 201 and replacement.json()["quota_used"] == 0
            assert (await Tenant.get(id=tenant.id)).quota_used == Decimal("0.015")
            assert (await client.get("/v1/models", headers=application)).status_code == 401
        print("PASS: platform and tenant login, temporary password, JWT revocation, key CRUD, isolation,")
        print("      real inference, MySQL/Redis accounting, quota idempotence/rejection, disable and replacement")
    finally:
        upstream.shutdown()
        keys = list(await APIKey.filter(tenant_id__in=tenant_ids).values_list("id", flat=True)) + platform_key_ids
        await RequestLog.filter(api_key_id__in=keys).delete()
        await UsageDaily.filter(api_key_id__in=keys).delete()
        await Settlement.filter(api_key_id__in=keys).delete()
        await APIKey.filter(id__in=keys).delete()
        await User.filter(tenant_id__in=tenant_ids).delete()
        await Tenant.filter(id__in=tenant_ids).delete()
        if channel_id:
            await ModelProbe.filter(channel_id=channel_id).delete()
            await Channel.filter(id=channel_id).delete()
        if price_id:
            await ModelPrice.filter(id=price_id).delete()
        if operator:
            await ManagementEvent.filter(actor_id=operator.id).delete()
            await operator.delete()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(run())
