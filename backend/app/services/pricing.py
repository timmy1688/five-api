import re
from decimal import Decimal

USD_STEP = Decimal("0.000001")
# Upstreams bill an inline image, audio clip or file per item, so a base64
# payload counts as one large image instead of one token per four characters.
BLOB_TOKENS = 1600
_BLOB_MIN_CHARS = 1024
_BASE64 = re.compile(r"[A-Za-z0-9+/=_-]+")


def catalog_prices(model: str) -> dict[str, float]:
    """Input, output, cache-read, and cache-write prices per 1M tokens, plus a per-request price.

    Anthropic bills a 5-minute cache write at 1.25 times the input price.
    Other vendors bill that write as ordinary input. An explicit catalog
    cache_write overrides the multiplier.
    """
    raw = DEFAULT_MODEL_PRICES[model]
    prompt = float(raw["prompt"])
    if "cache_write" in raw:
        write = float(raw["cache_write"])
    elif model.startswith("claude-"):
        write = prompt * 1.25
    else:
        write = prompt
    return {
        "prompt": prompt,
        "completion": float(raw["completion"]),
        "cached": float(raw.get("cached", 0)),
        "cache_write": write,
        "request": float(raw.get("request", 0)),
    }


def estimate_request_tokens(
    body: dict | None, default_output: int | None = None,
) -> tuple[int, int]:
    """Upper-bound input tokens and the requested output cap.

    CJK characters count as one token. Other text counts as four characters
    per token. Output uses the request's cap. Without one, chat requests use
    4096 and the caller may pass its own default.
    """
    if not body:
        return 1, 0
    raw_out = next(
        (
            body[name] for name in ("max_tokens", "max_completion_tokens", "max_output_tokens")
            if body.get(name) is not None
        ),
        None,
    )
    if raw_out is None:
        if default_output is not None:
            output = default_output
        else:
            output = 4096 if body.get("messages") or body.get("system") else 0
    else:
        try:
            output = int(raw_out)
        except (TypeError, ValueError):
            output = 4096
    output = max(output, 0)
    text_parts = (
        body.get("messages"),
        body.get("system"),
        body.get("instructions"),
        body.get("prompt"),
        body.get("input"),
        body.get("query"),
        body.get("documents"),
        body.get("tools"),
    )
    input_tokens = max(1, count_text_tokens(text_parts))
    return input_tokens, output


def count_text_tokens(value) -> int:
    """Rough token count of every string inside value.

    CJK characters count as one token. Other text counts as four characters
    per token. Used when an upstream does not report usage.
    """
    cjk = 0
    other = 0
    blobs = 0
    explicit_tokens = 0

    def walk(item) -> None:
        nonlocal cjk, other, blobs, explicit_tokens
        if isinstance(item, str):
            if _is_blob(item):
                blobs += 1
                return
            for char in item:
                if "\u4e00" <= char <= "\u9fff":
                    cjk += 1
                else:
                    other += 1
            return
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
            return
        if isinstance(item, (list, tuple)):
            if item and all(type(child) is int for child in item):
                explicit_tokens += len(item)
                return
            for child in item:
                walk(child)

    walk(value)
    return cjk + (other + 3) // 4 + blobs * BLOB_TOKENS + explicit_tokens


def _is_blob(text: str) -> bool:
    if len(text) < _BLOB_MIN_CHARS:
        return False
    head = text[:_BLOB_MIN_CHARS]
    return head.startswith("data:") or _BASE64.fullmatch(head) is not None


MODEL_PRICE_CATALOG_VERSION = "2026-10-18.2"

# Standard USD prices per 1M tokens. For providers with regional or context-tiered
# pricing, this catalog uses the standard short-context price.
DEFAULT_MODEL_PRICES: dict[str, dict[str, float]] = {
    # ── OpenAI GPT-5.x ──
    "gpt-5.6": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.6-sol": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.6-terra": {"prompt": 2.5, "completion": 15.0, "cached": 0.25},
    "gpt-5.6-luna": {"prompt": 1.0, "completion": 6.0, "cached": 0.1},
    # Video is billed per second of output; the request price is per second.
    "sora-2": {"prompt": 0.0, "completion": 0.0, "request": 0.10},
    "sora-2-pro": {"prompt": 0.0, "completion": 0.0, "request": 0.30},
    "gpt-5.5": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.5-2026-04-23": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.5-pro": {"prompt": 30.0, "completion": 180.0, "cached": 3.0},
    "gpt-5.5-pro-2026-04-23": {"prompt": 30.0, "completion": 180.0, "cached": 3.0},
    "gpt-5.4": {"prompt": 2.5, "completion": 15.0, "cached": 0.25},
    "gpt-5.4-2026-03-05": {"prompt": 2.5, "completion": 15.0, "cached": 0.25},
    "gpt-5.4-mini": {"prompt": 0.75, "completion": 4.5, "cached": 0.075},
    "gpt-5.4-mini-2026-03-17": {"prompt": 0.75, "completion": 4.5, "cached": 0.075},
    "gpt-5.4-nano": {"prompt": 0.2, "completion": 1.25, "cached": 0.02},
    "gpt-5.4-nano-2026-03-17": {"prompt": 0.2, "completion": 1.25, "cached": 0.02},
    "gpt-5": {"prompt": 1.25, "completion": 10.0, "cached": 0.125},
    "gpt-5-2025-08-07": {"prompt": 1.25, "completion": 10.0, "cached": 0.125},
    "gpt-5-pro": {"prompt": 15.0, "completion": 120.0, "cached": 0},
    "gpt-5-pro-2025-10-06": {"prompt": 15.0, "completion": 120.0, "cached": 0},
    "gpt-5-mini": {"prompt": 0.25, "completion": 2.0, "cached": 0.025},
    "gpt-5-mini-2025-08-07": {"prompt": 0.25, "completion": 2.0, "cached": 0.025},
    "gpt-5-nano": {"prompt": 0.05, "completion": 0.4, "cached": 0.005},
    "gpt-5-nano-2025-08-07": {"prompt": 0.05, "completion": 0.4, "cached": 0.005},
    # ── OpenAI GPT-4.x ──
    "gpt-4.1": {"prompt": 2.0, "completion": 8.0, "cached": 0.5},
    "gpt-4.1-mini": {"prompt": 0.4, "completion": 1.6, "cached": 0.1},
    "gpt-4.1-nano": {"prompt": 0.1, "completion": 0.4, "cached": 0.025},
    "gpt-4o": {"prompt": 2.5, "completion": 10.0, "cached": 1.25},
    "gpt-4o-2024-11-20": {"prompt": 2.5, "completion": 10.0, "cached": 1.25},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.6, "cached": 0.075},
    "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0, "cached": 5.0},
    # ── OpenAI o-series（reasoning）──
    "o3": {"prompt": 2.0, "completion": 8.0, "cached": 0.5},
    "o3-pro": {"prompt": 20.0, "completion": 80.0, "cached": 10.0},
    "o4-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.275},
    "o3-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.55},
    "o1": {"prompt": 15.0, "completion": 60.0, "cached": 7.5},
    "o1-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.55},
    # ── Anthropic Claude (4.6+ IDs are intentionally dateless snapshots) ──
    "claude-fable-5": {"prompt": 10.0, "completion": 50.0, "cached": 1.0},
    "claude-mythos-5": {"prompt": 10.0, "completion": 50.0, "cached": 1.0},
    "claude-opus-5": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-sonnet-5": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-opus-4-8": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-opus-4-7": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-opus-4-6": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-opus-4-5-20251101": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-sonnet-4-6": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-sonnet-4-5-20250929": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-haiku-4-5-20251001": {"prompt": 1.0, "completion": 5.0, "cached": 0.1},
    "claude-haiku-4-5": {"prompt": 1.0, "completion": 5.0, "cached": 0.1},
    # ── Google Gemini 3.x ──
    "gemini-3.6-flash": {"prompt": 1.5, "completion": 7.5, "cached": 0.15},
    "gemini-3.5-flash": {"prompt": 1.5, "completion": 9.0, "cached": 0.15},
    "gemini-3.5-flash-lite": {"prompt": 0.3, "completion": 2.5, "cached": 0.03},
    "gemini-3.1-pro-preview": {"prompt": 2.0, "completion": 12.0, "cached": 0.2},
    "gemini-3-flash-preview": {"prompt": 0.5, "completion": 3.0, "cached": 0.05},
    "gemini-3.1-flash-lite": {"prompt": 0.25, "completion": 1.5, "cached": 0.025},
    # ── Google Gemini 2.x ──
    "gemini-2.5-pro": {"prompt": 1.25, "completion": 10.0, "cached": 0.125},
    "gemini-2.5-flash": {"prompt": 0.3, "completion": 2.5, "cached": 0.03},
    "gemini-2.5-flash-lite": {"prompt": 0.1, "completion": 0.4, "cached": 0.01},
    "gemini-2.0-flash": {"prompt": 0.1, "completion": 0.4, "cached": 0.01},
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.0, "cached": 0.3125},
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.3, "cached": 0.01875},
    # ── Alibaba Qwen (global deployment, first context tier) ──
    "qwen3.7-max": {"prompt": 1.65, "completion": 4.951, "cached": 0.165},
    "qwen3.7-max-2026-06-08": {"prompt": 1.65, "completion": 4.951, "cached": 0.165},
    "qwen3.7-max-2026-05-20": {"prompt": 1.65, "completion": 4.951, "cached": 0.165},
    "qwen3.7-plus": {"prompt": 0.276, "completion": 1.101, "cached": 0.0276},
    "qwen3.7-plus-2026-05-26": {"prompt": 0.276, "completion": 1.101, "cached": 0.0276},
    "qwen3.6-plus": {"prompt": 0.276, "completion": 1.651, "cached": 0.0276},
    "qwen3.6-plus-2026-04-02": {"prompt": 0.276, "completion": 1.651, "cached": 0.0276},
    "qwen3.6-flash": {"prompt": 0.165, "completion": 0.99, "cached": 0.0165},
    "qwen3.6-flash-2026-04-16": {"prompt": 0.165, "completion": 0.99, "cached": 0.0165},
    "qwen3-max": {"prompt": 0.359, "completion": 1.434, "cached": 0.0359},
    "qwen3-max-2026-01-23": {"prompt": 0.359, "completion": 1.434, "cached": 0.0359},
    "qwen-max": {"prompt": 1.6, "completion": 6.4, "cached": 0.16},
    "qwen-plus": {"prompt": 0.26, "completion": 0.78, "cached": 0.026},
    "qwen-turbo": {"prompt": 0.3, "completion": 0.6, "cached": 0.03},
    "qwen-long": {"prompt": 0.5, "completion": 2.0, "cached": 0.05},
    # ── DeepSeek V4 ──
    # Peak rates. Off-peak is half; the gateway bills one rate per model, so
    # off-peak traffic is charged at the higher price.
    "deepseek-flash": {"prompt": 0.3, "completion": 1.2, "cached": 0.006},
    "deepseek-v4-flash": {"prompt": 0.3, "completion": 1.2, "cached": 0.006},
    "deepseek-v4-pro": {"prompt": 1.32, "completion": 3.96, "cached": 0.044},
    "deepseek-r1": {"prompt": 0.55, "completion": 2.19, "cached": 0.055},
    # ── xAI Grok (short context) ──
    "grok-4.5": {"prompt": 2.0, "completion": 6.0, "cached": 0.3},
    "grok-4.3": {"prompt": 1.25, "completion": 2.5, "cached": 0.2},
    "grok-4.20": {"prompt": 1.25, "completion": 2.5, "cached": 0.2},
    "grok-4.20-0309-reasoning": {"prompt": 1.25, "completion": 2.5, "cached": 0.2},
    "grok-4.20-0309-non-reasoning": {"prompt": 1.25, "completion": 2.5, "cached": 0.2},
    "grok-4.20-multi-agent-0309": {"prompt": 1.25, "completion": 2.5, "cached": 0.2},
    "grok-build-0.1": {"prompt": 1.0, "completion": 2.0, "cached": 0.2},
    # ── Mistral ──
    "mistral-large-2512": {"prompt": 0.5, "completion": 1.5, "cached": 0},
}
