"""Repeatable direct-vs-gateway HTTP benchmark using disposable synthetic data."""
import argparse
import asyncio
import json
import os
import platform
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
from tortoise import Tortoise

from app.config import TORTOISE_ORM
from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily, ModelProbe
from app.services.auth import hash_api_key


def percentile(values, quantile):
    values = sorted(values)
    index = (len(values)-1) * quantile
    low = int(index)
    high = min(low+1, len(values)-1)
    return round(values[low] + (values[high]-values[low]) * (index-low), 3)


async def measure(client, url, body, headers, count, concurrency):
    semaphore = asyncio.Semaphore(concurrency)
    durations, errors = [], 0
    async def one():
        nonlocal errors
        async with semaphore:
            begin = time.perf_counter()
            try:
                response = await client.post(url, json=body, headers=headers)
                errors += int(response.status_code != 200)
            except httpx.RequestError:
                errors += 1
            durations.append((time.perf_counter()-begin)*1000)
    begin = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(count)))
    elapsed = time.perf_counter()-begin
    return {"requests": count, "errors": errors, "elapsed_seconds": round(elapsed, 3),
            "requests_per_second": round(count/elapsed, 2), "p50_ms": percentile(durations, .5),
            "p95_ms": percentile(durations, .95)}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--upstream-ms", type=float, default=5)
    parser.add_argument("--gateway", default="http://127.0.0.1:5002")
    parser.add_argument("--output", default="../docs/benchmarks/latest.json")
    args = parser.parse_args()
    if not 1 <= args.requests <= 10000 or not 1 <= args.concurrency <= 100 or not 0 <= args.upstream_ms <= 1000:
        parser.error("Use 1..10000 requests, 1..100 concurrency and 0..1000 upstream-ms")
    model = "five-benchmark-" + uuid4().hex[:12]
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            time.sleep(args.upstream_ms / 1000)
            data = json.dumps({"choices": [{"message": {"role": "assistant", "content": "synthetic response"}}],
                               "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *_):
            pass
    origin = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    await Tortoise.init(config=TORTOISE_ORM)
    tenant = channel = price = key = None
    try:
        tenant = await Tenant.create(name=model, quota_total=-1, rpm_limit=-1, tpm_limit=-1, concurrent_limit=-1)
        raw = "sk-" + secrets.token_urlsafe(32)
        key = await APIKey.create(tenant_id=tenant.id, name=model, key_hash=hash_api_key(raw), key_prefix=raw[:8],
                                  quota_total=-1, rpm_limit=-1, tpm_limit=-1, concurrent_limit=100)
        upstream = f"http://127.0.0.1:{origin.server_port}"
        channel = await Channel.create(name=model, provider="openai", base_url=upstream, api_key="", models=[model], priority=10000)
        price = await ModelPrice.create(model=model)  # explicit zero; no vendor calls or customer charges
        body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "synthetic benchmark"}]}
        limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
        async with httpx.AsyncClient(trust_env=False, timeout=30, limits=limits) as client:
            gateway_headers = {"Authorization": "Bearer " + raw}
            direct_url, gateway_url = upstream + "/v1/chat/completions", args.gateway + "/v1/chat/completions"
            await measure(client, direct_url, body, {}, 3, 1)
            await measure(client, gateway_url, body, gateway_headers, 3, 1)
            direct = await measure(client, direct_url, body, {}, args.requests, args.concurrency)
            gateway = await measure(client, gateway_url, body, gateway_headers, args.requests, args.concurrency)
        report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "version": "0.4.0", "python": platform.python_version(), "platform": platform.platform(),
                  "cpu_count": os.cpu_count(), "concurrency": args.concurrency, "upstream_delay_ms": args.upstream_ms,
                  "conditions": "Single local dev worker with MySQL/Redis; synthetic JSON; zero pricing; sequential runs after warmup; not production capacity",
                  "direct": direct, "gateway": gateway,
                  "added_p50_ms": round(gateway["p50_ms"]-direct["p50_ms"], 3),
                  "added_p95_ms": round(gateway["p95_ms"]-direct["p95_ms"], 3)}
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        assert direct["errors"] == gateway["errors"] == 0, "Benchmark requests failed"
    finally:
        if key:
            await RequestLog.filter(api_key_id=key.id).delete()
            await UsageDaily.filter(api_key_id=key.id).delete()
            await Settlement.filter(api_key_id=key.id).delete()
            await key.delete()
        if channel:
            await ModelProbe.filter(channel_id=channel.id).delete()
            await channel.delete()
        if price:
            await price.delete()
        if tenant:
            await tenant.delete()
        await Tortoise.close_connections()
        origin.shutdown()
        origin.server_close()


if __name__ == "__main__":
    asyncio.run(main())
