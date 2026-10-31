"""Repeatable gateway throughput benchmark across worker counts, using disposable synthetic data.

The synthetic upstream and the load generator run in their own processes so they are not
the bottleneck. Each gateway run starts `uvicorn --workers N` against the configured
database, checks that every successful request was billed exactly once, and removes the
data it created.
"""
import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import secrets
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from tortoise import Tortoise

from app.config import TORTOISE_ORM
from app.models import APIKey, Channel, ModelPrice, ModelProbe, RequestLog, Settlement, Tenant, UsageDaily
from app.services.auth import hash_api_key

ROOT = Path(__file__).resolve().parents[1]
RESPONSE = json.dumps({"choices": [{"message": {"role": "assistant", "content": "synthetic response"}}],
                       "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode()


async def upstream_app(scope, receive, send):
    """Minimal OpenAI-compatible origin with a fixed delay, served by its own Uvicorn process."""
    if scope["type"] != "http":
        return
    while (await receive()).get("more_body"):
        pass
    await asyncio.sleep(float(os.environ.get("BENCH_UPSTREAM_MS", "5")) / 1000)
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(RESPONSE)).encode())]})
    await send({"type": "http.response.body", "body": RESPONSE})


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def start(args, env) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "uvicorn", *args, "--host", "127.0.0.1", "--no-access-log",
                             "--log-level", "warning"], cwd=ROOT, env={**os.environ, **env},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


async def wait_ready(url: str, process: subprocess.Popen) -> None:
    async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
        for _ in range(300):
            if process.poll() is not None:
                raise RuntimeError(f"Process exited before {url} was ready")
            try:
                await client.get(url)
                return
            except httpx.RequestError:
                await asyncio.sleep(0.1)
    raise RuntimeError(f"{url} never became ready")


def percentile(values, quantile):
    values = sorted(values)
    index = (len(values) - 1) * quantile
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return round(values[low] + (values[high] - values[low]) * (index - low), 2)


def load_shard(url, body, headers, count, concurrency, offset):
    """One load-generator process; requests rotate over the given keys. Returns latencies in ms and errors."""
    async def run():
        durations, errors = [], 0
        semaphore = asyncio.Semaphore(concurrency)
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        async with httpx.AsyncClient(trust_env=False, timeout=60, limits=limits) as client:
            async def one(index):
                nonlocal errors
                async with semaphore:
                    begin = time.perf_counter()
                    try:
                        response = await client.post(url, json=body, headers=headers[(offset + index) % len(headers)])
                        errors += int(response.status_code != 200)
                    except httpx.RequestError:
                        errors += 1
                    durations.append((time.perf_counter() - begin) * 1000)
            await asyncio.gather(*(one(index) for index in range(count)))
        return durations, errors
    return asyncio.run(run())


def measure(pool, clients, url, body, headers, requests, concurrency):
    shards = [(url, body, headers, requests // clients + (index < requests % clients),
               max(1, concurrency // clients + (index < concurrency % clients)), index)
              for index in range(clients)]
    begin = time.perf_counter()
    results = pool.starmap(load_shard, shards)
    elapsed = time.perf_counter() - begin
    durations = [value for shard, _ in results for value in shard]
    errors = sum(count for _, count in results)
    return {"requests": requests, "errors": errors, "elapsed_seconds": round(elapsed, 2),
            "requests_per_second": round(requests / elapsed, 1),
            "p50_ms": percentile(durations, .5), "p95_ms": percentile(durations, .95),
            "p99_ms": percentile(durations, .99)}


async def settled(key_ids: list[int], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while await Settlement.filter(api_key_id__in=key_ids).exclude(state__in=("settled", "released")).exists():
        if time.monotonic() > deadline:
            return
        await asyncio.sleep(0.2)


async def key_totals(key_ids: list[int]) -> Decimal:
    return sum(await APIKey.filter(id__in=key_ids).values_list("quota_used", flat=True), Decimal(0))


async def billed_exactly_once(key_ids: list[int], before: Decimal) -> dict:
    """Every successful request settled once and the key totals grew by exactly the logged charges."""
    logs = await RequestLog.filter(api_key_id__in=key_ids, status_code=200).count()
    charged = sum(await RequestLog.filter(api_key_id__in=key_ids).values_list("cost", flat=True), Decimal(0))
    settled = await Settlement.filter(api_key_id__in=key_ids, state="settled").count()
    open_states = await Settlement.filter(api_key_id__in=key_ids).exclude(state__in=("settled", "released")).count()
    return {"settled": settled, "success_logs": logs, "open_settlements": open_states,
            "ok": settled == logs and open_states == 0 and await key_totals(key_ids) - before == charged}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", default="1,2,4", help="Comma-separated gateway worker counts")
    parser.add_argument("--tenants", type=int, default=16, help="Tenants, one key each; requests rotate over them")
    parser.add_argument("--requests", type=int, default=4000)
    parser.add_argument("--warmup", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--clients", type=int, default=4, help="Load-generator processes")
    parser.add_argument("--upstream-ms", type=float, default=5)
    parser.add_argument("--output", help="Also write the JSON report to this file")
    args = parser.parse_args()
    counts = [int(value) for value in args.workers.split(",")]
    if not all(1 <= count <= 16 for count in counts) or not 1 <= args.tenants <= 256 \
            or not 1 <= args.requests <= 100000 or not 1 <= args.concurrency <= 1000 \
            or not 1 <= args.clients <= 16 or not 0 <= args.upstream_ms <= 1000:
        parser.error("Use 1..16 workers, 1..256 tenants, 1..100000 requests, 1..1000 concurrency, "
                     "1..16 clients, 0..1000 upstream-ms")
    model = "five-benchmark-" + uuid4().hex[:12]
    upstream_port = free_port()
    origin = start(["scripts.benchmark:upstream_app", "--port", str(upstream_port)],
                   {"BENCH_UPSTREAM_MS": str(args.upstream_ms)})
    upstream = f"http://127.0.0.1:{upstream_port}"
    await Tortoise.init(config=TORTOISE_ORM)
    tenant_ids, key_ids, channel, price = [], [], None, None
    pool = multiprocessing.get_context("spawn").Pool(args.clients)
    try:
        await wait_ready(upstream, origin)
        auth = []
        for index in range(args.tenants):
            tenant = await Tenant.create(name=f"{model}-{index}", quota_total=-1, rpm_limit=-1, tpm_limit=-1,
                                         concurrent_limit=-1)
            tenant_ids.append(tenant.id)
            raw = "sk-" + secrets.token_urlsafe(32)
            key = await APIKey.create(tenant_id=tenant.id, name=model, key_hash=hash_api_key(raw),
                                      key_prefix=raw[:8], quota_total=-1, rpm_limit=-1, tpm_limit=-1,
                                      concurrent_limit=-1)
            key_ids.append(key.id)
            auth.append({"Authorization": "Bearer " + raw})
        channel = await Channel.create(name=model, provider="openai", base_url=upstream, api_key="", models=[model],
                                       priority=10000)
        # A real price so the run also proves billing; the synthetic tenants are never invoiced.
        price = await ModelPrice.create(model=model, prompt_price=Decimal("1"), completion_price=Decimal("2"))
        body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": "synthetic benchmark"}]}
        direct_url = upstream + "/v1/chat/completions"
        measure(pool, args.clients, direct_url, body, [{}], args.warmup, args.concurrency)
        direct = measure(pool, args.clients, direct_url, body, [{}], args.requests, args.concurrency)
        runs = []
        for count in counts:
            port = free_port()
            gateway = start(["app.main:app", "--port", str(port), "--workers", str(count)], {"WORKERS": str(count)})
            try:
                await wait_ready(f"http://127.0.0.1:{port}/healthz", gateway)
                url = f"http://127.0.0.1:{port}/v1/chat/completions"
                measure(pool, args.clients, url, body, auth, args.warmup, args.concurrency)
                await settled(key_ids)
                before = await key_totals(key_ids)
                await RequestLog.filter(api_key_id__in=key_ids).delete()
                await Settlement.filter(api_key_id__in=key_ids).delete()
                result = measure(pool, args.clients, url, body, auth, args.requests, args.concurrency)
                await settled(key_ids)
                result = {"workers": count, **result, "billing": await billed_exactly_once(key_ids, before)}
            finally:
                stop(gateway)
            runs.append(result)
            print(json.dumps(result), flush=True)
        base = runs[0]["requests_per_second"]
        for run in runs:
            run["speedup"] = round(run["requests_per_second"] / base, 2)
        report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "version": "0.4.0",
                  "python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(),
                  "tenants": args.tenants, "concurrency": args.concurrency, "requests": args.requests,
                  "upstream_delay_ms": args.upstream_ms, "load_processes": args.clients,
                  "conditions": "Gateway, synthetic upstream, load generator, MySQL and Redis share one host; "
                                "uvicorn --workers N without --reload; synthetic JSON; not production capacity",
                  "direct": direct, "gateway": runs}
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        assert all(run["errors"] == 0 and run["billing"]["ok"] for run in runs), "Benchmark errors or billing mismatch"
    finally:
        pool.terminate()
        if key_ids:
            await RequestLog.filter(api_key_id__in=key_ids).delete()
            await UsageDaily.filter(api_key_id__in=key_ids).delete()
            await Settlement.filter(api_key_id__in=key_ids).delete()
            await APIKey.filter(id__in=key_ids).delete()
        if channel:
            await ModelProbe.filter(channel_id=channel.id).delete()
            await channel.delete()
        if price:
            await price.delete()
        if tenant_ids:
            await Tenant.filter(id__in=tenant_ids).delete()
        await Tortoise.close_connections()
        stop(origin)

if __name__ == "__main__":
    asyncio.run(main())
