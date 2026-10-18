"""Add Anthropic prompt cache breakpoints for clients that never set any.

Anthropic only caches up to a block marked with cache_control. Many SDK apps
never mark one, so every turn pays full input price for the same prefix.
Three breakpoints cover the usual layout: tool definitions, the system
prompt, and the newest message, so the next turn reads everything before it
from cache. Anthropic allows four and ignores prefixes under its minimum size.
"""

import copy
from typing import Any

BREAKPOINT = {"type": "ephemeral"}
# Blocks Anthropic rejects cache_control on.
_UNCACHEABLE = {"thinking", "redacted_thinking"}


def _has_cache_control(value: Any) -> bool:
    if isinstance(value, dict):
        return "cache_control" in value or any(_has_cache_control(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_cache_control(v) for v in value)
    return False


def _mark_last_block(blocks: list) -> bool:
    for block in reversed(blocks):
        if isinstance(block, dict) and block.get("type") not in _UNCACHEABLE:
            block["cache_control"] = dict(BREAKPOINT)
            return True
    return False


def with_cache_control(body: dict) -> tuple[dict, bool]:
    """Return a copy with breakpoints added, and whether anything changed."""
    if not isinstance(body, dict) or _has_cache_control(body):
        return body, False
    out = copy.deepcopy(body)
    changed = False

    tools = out.get("tools")
    if isinstance(tools, list) and tools and isinstance(tools[-1], dict):
        tools[-1]["cache_control"] = dict(BREAKPOINT)
        changed = True

    system = out.get("system")
    if isinstance(system, str) and system.strip():
        out["system"] = [{"type": "text", "text": system, "cache_control": dict(BREAKPOINT)}]
        changed = True
    elif isinstance(system, list):
        changed = _mark_last_block(system) or changed

    messages = out.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        last = messages[-1]
        content = last.get("content")
        if isinstance(content, str) and content:
            last["content"] = [{"type": "text", "text": content, "cache_control": dict(BREAKPOINT)}]
            changed = True
        elif isinstance(content, list):
            changed = _mark_last_block(content) or changed

    return (out, True) if changed else (body, False)
