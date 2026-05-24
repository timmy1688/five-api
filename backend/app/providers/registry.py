import random

from fastapi import HTTPException

from app.models import Channel
from app.providers.base import BaseProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.qwen_provider import QwenProvider
from app.providers.azure_provider import AzureProvider

PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "qwen": QwenProvider,
    "azure": AzureProvider,
}


def _weighted_shuffle(channels: list[Channel]) -> list[Channel]:
    """按 weight 加权随机排序，高权重的排在前面概率更大。"""
    remaining = list(channels)
    result = []
    while remaining:
        weights = [ch.weight for ch in remaining]
        total = sum(weights)
        if total == 0:
            idx = random.randrange(len(remaining))
        else:
            r = random.uniform(0, total)
            cumulative = 0
            idx = 0
            for i, w in enumerate(weights):
                cumulative += w
                if r <= cumulative:
                    idx = i
                    break
        result.append(remaining.pop(idx))
    return result


async def resolve_candidates(model: str, channel_group: str = "") -> list[tuple[Channel, type[BaseProvider]]]:
    """返回所有支持该模型的候选渠道，按 priority 降序分层，同层按 weight 加权随机排序。

    channel_group 为空时可访问所有渠道，非空时只能访问 group 为空或匹配的渠道。
    """
    from app.services.channel_health import is_channel_healthy

    channels = await Channel.filter(is_enabled=True)
    candidates = [ch for ch in channels if model in (ch.models or [])]

    # 按分组过滤
    if channel_group:
        candidates = [ch for ch in candidates if not ch.group or ch.group == channel_group]

    # 过滤掉被熔断的渠道
    healthy_candidates = []
    for ch in candidates:
        if await is_channel_healthy(ch.id):
            healthy_candidates.append(ch)

    # 如果所有渠道都被熔断，降级使用全部候选（避免完全无法服务）
    if not healthy_candidates and candidates:
        healthy_candidates = candidates

    if not healthy_candidates:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "message": f"No channel available for model: {model}",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )

    tiers: dict[int, list[Channel]] = {}
    for ch in healthy_candidates:
        tiers.setdefault(ch.priority, []).append(ch)

    ordered_tiers = sorted(tiers.keys(), reverse=True)

    result: list[tuple[Channel, type[BaseProvider]]] = []
    for priority in ordered_tiers:
        tier_channels = tiers[priority]
        shuffled = _weighted_shuffle(tier_channels)
        for ch in shuffled:
            provider_cls = PROVIDER_MAP.get(ch.provider)
            if provider_cls is None:
                continue
            result.append((ch, provider_cls))

    if not result:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": "No supported provider found for model",
                    "type": "server_error",
                    "code": "unsupported_provider",
                }
            },
        )

    return result


async def resolve_channel(model: str) -> tuple[Channel, BaseProvider]:
    """返回第一个候选渠道（最高优先级、加权随机）。保持向后兼容。"""
    candidates = await resolve_candidates(model)
    channel, provider_cls = candidates[0]
    return channel, provider_cls(channel)


async def list_available_models() -> list[dict]:
    channels = await Channel.filter(is_enabled=True)
    seen = set()
    models = []
    for ch in channels:
        for m in ch.models or []:
            if m not in seen:
                seen.add(m)
                models.append({"id": m, "object": "model", "owned_by": ch.provider})
    return models
