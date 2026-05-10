from decimal import Decimal

from app.models import Channel, ModelPrice

MILLION = Decimal("1000000")


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

    if channel and channel.model_pricing:
        pricing = channel.model_pricing.get(model)
        if pricing:
            prompt_price = Decimal(str(pricing.get("prompt", 0)))
            completion_price = Decimal(str(pricing.get("completion", 0)))
            cached_price = Decimal(str(pricing.get("cached", 0)))

    if prompt_price == 0 and completion_price == 0:
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


DEFAULT_MODEL_PRICES: dict[str, dict[str, float]] = {
    # ── OpenAI GPT-5.x ──
    "gpt-5.5": {"prompt": 5.0, "completion": 30.0, "cached": 1.25},
    "gpt-5.4": {"prompt": 2.5, "completion": 15.0, "cached": 0.625},
    "gpt-5.4-mini": {"prompt": 0.75, "completion": 4.5, "cached": 0.1875},
    "gpt-5.4-nano": {"prompt": 0.2, "completion": 1.25, "cached": 0.05},
    "gpt-5": {"prompt": 1.25, "completion": 10.0, "cached": 0.3125},
    "gpt-5-mini": {"prompt": 0.25, "completion": 2.0, "cached": 0.0625},
    # ── OpenAI GPT-4.x ──
    "gpt-4.1": {"prompt": 2.0, "completion": 8.0, "cached": 0.5},
    "gpt-4.1-mini": {"prompt": 0.4, "completion": 1.6, "cached": 0.1},
    "gpt-4.1-nano": {"prompt": 0.1, "completion": 0.4, "cached": 0.025},
    "gpt-4o": {"prompt": 2.5, "completion": 10.0, "cached": 1.25},
    "gpt-4o-2024-11-20": {"prompt": 2.5, "completion": 10.0, "cached": 1.25},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.6, "cached": 0.075},
    "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0, "cached": 5.0},
    # ── OpenAI o-series reasoning ──
    "o3": {"prompt": 2.0, "completion": 8.0, "cached": 0.5},
    "o3-pro": {"prompt": 20.0, "completion": 80.0, "cached": 10.0},
    "o4-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.275},
    "o3-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.55},
    "o1": {"prompt": 15.0, "completion": 60.0, "cached": 7.5},
    "o1-mini": {"prompt": 1.1, "completion": 4.4, "cached": 0.55},
    "o1-pro": {"prompt": 150.0, "completion": 600.0, "cached": 75.0},
    # ── Anthropic Claude 4.x ──
    "claude-opus-4-20250514": {"prompt": 15.0, "completion": 75.0, "cached": 1.5},
    "claude-opus-4-6-20250610": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-opus-4-7-20260416": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-sonnet-4-20250514": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-sonnet-4-6-20250819": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-haiku-4-5-20251001": {"prompt": 1.0, "completion": 5.0, "cached": 0.1},
    # ── Anthropic Claude 3.x (legacy) ──
    "claude-3.5-sonnet-20241022": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-3.5-haiku-20241022": {"prompt": 0.8, "completion": 4.0, "cached": 0.08},
    "claude-3-opus-20240229": {"prompt": 15.0, "completion": 75.0, "cached": 1.5},
    # ── Anthropic short aliases ──
    "claude-opus-4": {"prompt": 15.0, "completion": 75.0, "cached": 1.5},
    "claude-opus-4-6": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-opus-4-7": {"prompt": 5.0, "completion": 25.0, "cached": 0.5},
    "claude-sonnet-4": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-sonnet-4-6": {"prompt": 3.0, "completion": 15.0, "cached": 0.3},
    "claude-haiku-4-5": {"prompt": 1.0, "completion": 5.0, "cached": 0.1},
    # ── Google Gemini ──
    "gemini-2.5-pro": {"prompt": 1.25, "completion": 10.0, "cached": 0.3125},
    "gemini-2.5-flash": {"prompt": 0.3, "completion": 2.5, "cached": 0.075},
    "gemini-2.5-flash-lite": {"prompt": 0.1, "completion": 0.4, "cached": 0.025},
    "gemini-2.0-flash": {"prompt": 0.1, "completion": 0.4, "cached": 0.025},
    "gemini-1.5-pro": {"prompt": 1.25, "completion": 5.0, "cached": 0.3125},
    "gemini-1.5-flash": {"prompt": 0.075, "completion": 0.3, "cached": 0.01875},
    # ── Alibaba Qwen ──
    "qwen3-max": {"prompt": 0.78, "completion": 3.9, "cached": 0.078},
    "qwen3.6-plus": {"prompt": 0.325, "completion": 1.95, "cached": 0.0325},
    "qwen-max": {"prompt": 2.0, "completion": 6.0, "cached": 0.2},
    "qwen-plus": {"prompt": 0.26, "completion": 0.78, "cached": 0.026},
    "qwen-turbo": {"prompt": 0.3, "completion": 0.6, "cached": 0.03},
    "qwen-long": {"prompt": 0.5, "completion": 2.0, "cached": 0.05},
    # ── DeepSeek ──
    "deepseek-chat": {"prompt": 0.27, "completion": 1.1, "cached": 0.07},
    "deepseek-reasoner": {"prompt": 0.55, "completion": 2.19, "cached": 0.14},
}
