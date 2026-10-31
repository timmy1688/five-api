"""Real-upstream test: the same streaming chat called directly and through the gateway.

It checks latency and billing under ordinary load, not capacity; vendors rate-limit their
accounts, so levels are capped at 200 and capacity is measured with scripts.benchmark.

Concurrency steps up level by level. At each level the upstream is called directly first and
then through a multi-worker gateway, so upstream or proxy limits are not mistaken for gateway
limits. A temporary tenant capped at a small budget is used; every gateway charge is recomputed
from the logged tokens and the model price, and the temporary data is removed afterwards.
"""
import argparse
import asyncio
import json
import multiprocessing
import secrets
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from tortoise import Tortoise

from app.config import TORTOISE_ORM
from app.models import APIKey, Channel, ModelPrice, RequestLog, Settlement, Tenant, UsageDaily
from app.services.auth import hash_api_key
from app.utils.secrets import channel_keys
from scripts.benchmark import free_port, start, stop, wait_ready

MILLION = Decimal(1_000_000)
TOLERANCE = Decimal("0.000002")
PROMPT = "Write a short paragraph about the sea."


def stream_shard(url, headers, body, count, concurrency, use_proxy, offset):
    """One load process; requests rotate over the given auth headers.
    Returns [(status, first_chunk_ms, total_ms)], status "ok" or an error label."""
    async def run():
        results = []
        semaphore = asyncio.Semaphore(concurrency)
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        timeout = httpx.Timeout(300, connect=30)
        async with httpx.AsyncClient(trust_env=use_proxy, timeout=timeout, limits=limits) as client:
            async def one(index):
                async with semaphore:
                    begin = time.perf_counter()
                    first = None
                    try:
                        async with client.stream("POST", url, json=body, headers=headers[(offset + index) % len(headers)]) as response:
                            if response.status_code != 200:
                                await response.aread()
                                results.append((str(response.status_code), None, None))
                                return
                            done = False
                            async for line in response.aiter_lines():
                                if first is None and line.startswith("data:"):
                                    first = (time.perf_counter() - begin) * 1000
                                if line.strip() == "data: [DONE]":
                                    done = True
                            total = (time.perf_counter() - begin) * 1000
                            results.append(("ok" if done else "incomplete", first, total))
                    except httpx.TimeoutException:
                        results.append(("timeout", None, None))
                    except httpx.HTTPError as exc:
                        results.append((type(exc).__name__, None, None))
            await asyncio.gather(*(one(index) for index in range(count)))
        return results
    return asyncio.run(run())


def percentile(values, share):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * share))]) if ordered else None


def run_level(pool, clients, url, headers, body, requests, concurrency, use_proxy):
    shards = [(url, headers, body, requests // clients + (index < requests % clients),
               max(1, concurrency // clients + (index < concurrency % clients)), use_proxy, index)
              for index in range(clients)]
    begin = time.perf_counter()
    results = [item for part in pool.starmap(stream_shard, shards) for item in part]
    elapsed = time.perf_counter() - begin
    ok = [item for item in results if item[0] == "ok"]
    return {"requests": len(results), "ok": len(ok),
            "errors": dict(Counter(item[0] for item in results if item[0] != "ok")),
            "success_rate": round(len(ok) / len(results) * 100, 1),
            "requests_per_minute": round(len(ok) / elapsed * 60),
            "first_token_p50_ms": percentile([item[1] for item in ok], 0.5),
            "first_token_p95_ms": percentile([item[1] for item in ok], 0.95),
            "total_p50_ms": percentile([item[2] for item in ok], 0.5),
            "total_p95_ms": percentile([item[2] for item in ok], 0.95)}


def expected_cost(log, price) -> Decimal:
    plain = max(0, log.prompt_tokens - log.cached_tokens - log.cache_write_tokens)
    return (plain * price.prompt_price + log.cached_tokens * price.cached_price
            + log.cache_write_tokens * price.cache_write_price
            + log.completion_tokens * price.completion_price) / MILLION


async def billing_check(key_ids: list[int], tenant_ids: list[int], price, sent: int, gateway_ok: int) -> dict:
    """Every request settled once, failures cost nothing, successes cost exactly tokens x price."""
    deadline = time.monotonic() + 120
    while await Settlement.filter(api_key_id__in=key_ids).exclude(state__in=("settled", "released")).exists():
        if time.monotonic() > deadline:
            break
        await asyncio.sleep(0.5)
    logs = await RequestLog.filter(api_key_id__in=key_ids)
    succeeded = [log for log in logs if log.status_code == 200]
    charged = sum((log.cost for log in logs), Decimal(0))
    key_used = sum(await APIKey.filter(id__in=key_ids).values_list("quota_used", flat=True), Decimal(0))
    tenant_used = sum(await Tenant.filter(id__in=tenant_ids).values_list("quota_used", flat=True), Decimal(0))
    result = {
        "requests_sent": sent,
        "request_logs": len(logs),
        "success_logs": len(succeeded),
        "settled": await Settlement.filter(api_key_id__in=key_ids, state__in=("settled", "released")).count(),
        "open_settlements": await Settlement.filter(api_key_id__in=key_ids)
                                            .exclude(state__in=("settled", "released")).count(),
        "failed_charged_usd": str(sum((log.cost for log in logs if log.status_code != 200), Decimal(0))),
        "prompt_tokens": sum(log.prompt_tokens for log in succeeded),
        "completion_tokens": sum(log.completion_tokens for log in succeeded),
        "usage_from_upstream": sum(log.usage_source == "upstream" for log in succeeded),
        "cost_mismatches": sum(abs(log.cost - expected_cost(log, price)) > TOLERANCE for log in succeeded),
        "charged_usd": str(charged),
        "key_used_usd": str(key_used),
        "tenant_used_usd": str(tenant_used),
    }
    result["ok"] = (result["request_logs"] == result["settled"] == sent and len(succeeded) == gateway_ok
                    and result["open_settlements"] == 0 and not result["cost_mismatches"]
                    and Decimal(result["failed_charged_usd"]) == 0
                    and key_used == charged == tenant_used)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, required=True, help="Existing OpenAI-compatible channel id")
    parser.add_argument("--model", required=True)
    parser.add_argument("--levels", default="10,20,50",
                        help="Comma-separated concurrency levels; keep below the vendor rate limit")
    parser.add_argument("--tenants", type=int, default=4, help="Gateway requests rotate over this many tenants")
    parser.add_argument("--per-level", type=int, default=4, help="Requests per level = level x this")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--clients", type=int, default=4, help="Load-generator processes")
    parser.add_argument("--budget", default="2", help="Temporary tenant quota in USD")
    parser.add_argument("--output", help="Also write the JSON report to this file")
    args = parser.parse_args()
    levels = [int(value) for value in args.levels.split(",")]
    if not all(1 <= level <= 200 for level in levels) or not 1 <= args.per_level <= 10 \
            or not 1 <= args.max_tokens <= 1024 or not 1 <= args.tenants <= 64 or not 1 <= args.workers <= 16 or not 1 <= args.clients <= 16:
        parser.error("Use 1..200 levels, 1..10 per-level, 1..1024 max-tokens, 1..64 tenants, "
                     "1..16 workers and clients")
    await Tortoise.init(config=TORTOISE_ORM)
    tenant_ids, key_ids, gateway = [], [], None
    pool = multiprocessing.get_context("spawn").Pool(args.clients)
    try:
        channel = await Channel.get(id=args.channel)
        price = await ModelPrice.get(model=args.model, is_active=True)
        if channel.provider != "openai" or not channel.is_enabled or args.model not in channel.models:
            raise SystemExit("The channel must be an enabled OpenAI-compatible channel serving the model")
        upstream_model = (channel.model_mapping or {}).get(args.model, args.model)
        name = "five-real-benchmark-" + uuid4().hex[:8]
        auth = []
        for index in range(args.tenants):
            tenant = await Tenant.create(name=f"{name}-{index}", quota_total=Decimal(args.budget) / args.tenants,
                                         rpm_limit=-1, tpm_limit=-1, concurrent_limit=-1)
            tenant_ids.append(tenant.id)
            raw = "sk-" + secrets.token_urlsafe(32)
            key = await APIKey.create(tenant_id=tenant.id, name=name, key_hash=hash_api_key(raw),
                                      key_prefix=raw[:8], quota_total=-1, rpm_limit=-1, tpm_limit=-1,
                                      concurrent_limit=-1, channel_ids=[channel.id])
            key_ids.append(key.id)
            auth.append({"Authorization": "Bearer " + raw})
        port = free_port()
        gateway = start(["app.main:app", "--port", str(port), "--workers", str(args.workers)],
                        {"WORKERS": str(args.workers)})
        await wait_ready(f"http://127.0.0.1:{port}/healthz", gateway)

        body = {"max_tokens": args.max_tokens, "stream": True, "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": PROMPT}]}
        direct = (channel.base_url.rstrip("/") + "/v1/chat/completions",
                  [{"Authorization": "Bearer " + channel_keys(channel.api_key)[0]}], {**body, "model": upstream_model})
        through = (f"http://127.0.0.1:{port}/v1/chat/completions", auth, {**body, "model": args.model})
        rows, sent, gateway_ok = [], 0, 0
        for level in levels:
            count = level * args.per_level
            # The upstream uses the host proxy settings, as the gateway does; the local gateway never does.
            row = {"concurrency": level,
                   "direct": run_level(pool, args.clients, *direct, count, level, True),
                   "gateway": run_level(pool, args.clients, *through, count, level, False)}
            sent += count
            gateway_ok += row["gateway"]["ok"]
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        report = {"date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "channel": channel.name,
                  "model": args.model, "workers": args.workers, "tenants": args.tenants, "stream": True, "max_tokens": args.max_tokens,
                  "requests_per_level": f"concurrency x {args.per_level}", "levels": rows,
                  "billing": await billing_check(key_ids, tenant_ids, price, sent, gateway_ok)}
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report["billing"], indent=2, ensure_ascii=False))
    finally:
        pool.terminate()
        if gateway:
            stop(gateway)
        if key_ids:
            await RequestLog.filter(api_key_id__in=key_ids).delete()
            await UsageDaily.filter(api_key_id__in=key_ids).delete()
            await Settlement.filter(api_key_id__in=key_ids).delete()
            await APIKey.filter(id__in=key_ids).delete()
        if tenant_ids:
            await Tenant.filter(id__in=tenant_ids).delete()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
