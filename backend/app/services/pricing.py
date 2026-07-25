from decimal import Decimal

from app.models import Channel, ModelPrice

MILLION = Decimal("1000000")


def find_channel_pricing(
    model: str,
    model_pricing: dict | None,
    model_mapping: dict | None,
) -> dict | None:
    """Find an explicit channel price by actual model name or its public alias."""
    pricing_map = model_pricing or {}
    if model in pricing_map:
        return pricing_map[model]
    alias = next(
        (
            source for source, target in (model_mapping or {}).items()
            if target == model and source in pricing_map
        ),
        None,
    )
    return pricing_map.get(alias) if alias else None


async def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    channel: Channel | None = None,
    cached_tokens: int = 0,
) -> Decimal:
    prompt_price = Decimal(0)
    completion_price = Decimal(0)
    cached_price = Decimal(0)

    has_channel_pricing = False
    if channel:
        pricing = find_channel_pricing(
            model, channel.model_pricing, channel.model_mapping
        )
        if pricing is not None:
            has_channel_pricing = True
            prompt_price = Decimal(str(pricing.get("prompt", 0)))
            completion_price = Decimal(str(pricing.get("completion", 0)))
            cached_price = Decimal(str(pricing.get("cached", 0)))

    if not has_channel_pricing:
        mp = await ModelPrice.get_or_none(model=model, is_active=True)
        if mp:
            prompt_price = Decimal(str(mp.prompt_price))
            completion_price = Decimal(str(mp.completion_price))
            cached_price = Decimal(str(mp.cached_price))

    non_cached = max(prompt_tokens - cached_tokens, 0)
    cost = (
        Decimal(non_cached) * prompt_price
        + Decimal(cached_tokens) * cached_price
        + Decimal(completion_tokens) * completion_price
    ) / MILLION
    return cost.quantize(Decimal("0.000001"))


MODEL_PRICE_CATALOG_VERSION = "2026-07-25"

# Standard USD prices per 1M tokens. For providers with regional or context-tiered
# pricing, this catalog uses the standard short-context price; channel pricing can
# override it when a deployment uses different rates.
DEFAULT_MODEL_PRICES: dict[str, dict[str, float]] = {
    # ── OpenAI GPT-5.x ──
    "gpt-5.6": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.6-sol": {"prompt": 5.0, "completion": 30.0, "cached": 0.5},
    "gpt-5.6-terra": {"prompt": 2.5, "completion": 15.0, "cached": 0.25},
    "gpt-5.6-luna": {"prompt": 1.0, "completion": 6.0, "cached": 0.1},
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
    "deepseek-v4-flash": {"prompt": 0.14, "completion": 0.28, "cached": 0.0028},
    "deepseek-v4-pro": {"prompt": 0.435, "completion": 0.87, "cached": 0.003625},
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
