import random

from fastapi import HTTPException

from app.models import Channel
from app.providers.base import BaseProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider

# 渠道只区分两种线协议：openai（含所有 OpenAI 兼容端点）与 anthropic
PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
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


OPENAI_PROTOCOL_PROVIDERS = {"openai"}
ANTHROPIC_PROTOCOL_PROVIDERS = {"anthropic"}


def _promote_sticky(
    result: list[tuple[Channel, type[BaseProvider]]],
    channel_id: int,
    preferred_providers: set[str] | None = None,
) -> list[tuple[Channel, type[BaseProvider]]]:
    """把粘性会话上次使用的渠道提到候选列表最前。

    仅当该渠道仍是健康候选（存在于列表中）时才提前；否则保持原序，
    让粘性绑定自然回退到正常路由。

    协议优先高于粘性：若粘性渠道不属于 preferred 协议组，但 preferred 组仍有
    健康渠道，则忽略粘性、回到协议优先排序（避免 preferred 渠道临时故障恢复后，
    会话被跨协议粘性长期卡在非优先渠道上）。此时下次请求成功会把粘性重绑回
    preferred 渠道，实现自愈。
    """
    idx = next((i for i, (ch, _) in enumerate(result) if ch.id == channel_id), None)
    if idx is None:
        return result

    sticky_ch = result[idx][0]
    if preferred_providers is not None and sticky_ch.provider not in preferred_providers:
        has_healthy_preferred = any(ch.provider in preferred_providers for ch, _ in result)
        if has_healthy_preferred:
            return result

    if idx != 0:
        result.insert(0, result.pop(idx))
    return result


async def resolve_candidates(
    model: str,
    preferred_protocol: str | None = None,
    sticky_channel_id: int | None = None,
) -> list[tuple[Channel, type[BaseProvider]]]:
    """返回所有支持该模型的候选渠道。

    排序：协议匹配的渠道整体排在前面，各组内按 priority 降序 + weight 加权随机。
    不匹配的渠道保留作为故障转移备选。
    若传入 sticky_channel_id 且该渠道仍健康，则将其提到最前（粘性会话）。
    """
    from app.services.channel_health import is_channel_healthy

    if preferred_protocol == "openai":
        preferred_providers = OPENAI_PROTOCOL_PROVIDERS
    elif preferred_protocol == "anthropic":
        preferred_providers = ANTHROPIC_PROTOCOL_PROVIDERS
    else:
        preferred_providers = None

    channels = await Channel.filter(is_enabled=True)
    candidates = [ch for ch in channels if model in (ch.models or [])]

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

    # 按协议匹配分成两组，各组内按 priority 分层 + weight 加权随机
    if preferred_providers:
        matched = [ch for ch in healthy_candidates if ch.provider in preferred_providers]
        unmatched = [ch for ch in healthy_candidates if ch.provider not in preferred_providers]
        groups = [matched, unmatched]
    else:
        groups = [healthy_candidates]

    result: list[tuple[Channel, type[BaseProvider]]] = []
    for group in groups:
        tiers: dict[int, list[Channel]] = {}
        for ch in group:
            tiers.setdefault(ch.priority, []).append(ch)
        for priority in sorted(tiers.keys(), reverse=True):
            for ch in _weighted_shuffle(tiers[priority]):
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

    if sticky_channel_id is not None:
        result = _promote_sticky(result, sticky_channel_id, preferred_providers)

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
