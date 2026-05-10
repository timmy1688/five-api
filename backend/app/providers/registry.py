import random

from fastapi import HTTPException

from app.models import Channel
from app.providers.base import BaseProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.qwen_provider import QwenProvider

PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "qwen": QwenProvider,
}


async def resolve_channel(model: str) -> tuple[Channel, BaseProvider]:
    channels = await Channel.filter(is_enabled=True)
    candidates = [ch for ch in channels if model in (ch.models or [])]

    if not candidates:
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

    max_priority = max(ch.priority for ch in candidates)
    top_tier = [ch for ch in candidates if ch.priority == max_priority]

    weights = [ch.weight for ch in top_tier]
    channel = random.choices(top_tier, weights=weights, k=1)[0]

    provider_cls = PROVIDER_MAP.get(channel.provider)
    if provider_cls is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": f"Unsupported provider: {channel.provider}",
                    "type": "server_error",
                    "code": "unsupported_provider",
                }
            },
        )

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
