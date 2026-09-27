"""关键词和密钥只做日志标记，不中断请求，也不改写回复。

关键词用字面量，只看请求。密钥扫描只用几条固定、线性的模式，请求和回复都看。
规则缓存在进程内，避免每个请求都读库。
"""

import json
import re
import time
from typing import Any

from app.models import SecurityKeyword
from app.services.audit import response_visible_text, sse_visible_text
from app.services.settings_service import keyword_filter_enabled, secret_scan_enabled

# 固定模式，没有嵌套量词。日志里只记名字，不记命中的密钥本身。
_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]{0,48}PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
)
_SECRET_TAIL = 180
_CACHE_TTL = 2.0
_cache: tuple[float, "FilterRules"] | None = None


class FilterRules:
    def __init__(
        self,
        enabled: bool,
        request_keywords: tuple[str, ...],
        response_keywords: tuple[str, ...],
        secret_scan: bool = False,
    ):
        self.enabled = enabled
        self.request_keywords = request_keywords
        self.response_keywords = response_keywords
        self.secret_scan = secret_scan

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.request_keywords or self.response_keywords)


def match_secret(text: str) -> str | None:
    if not text:
        return None
    for label, pattern in _SECRET_RULES:
        if pattern.search(text):
            return label
    return None


class ResponseScanner:
    """流式回复只保留一小段尾巴，避免每个分片都重扫整段输出。"""

    def __init__(self, keywords: tuple[str, ...], secrets: bool = False):
        self.keywords = keywords
        self.secrets = secrets
        self.tail = ""
        self.keep = max((len(keyword) for keyword in keywords), default=1) - 1
        self.secret_tail = ""

    def feed(self, piece: str) -> str | None:
        if not piece:
            return None
        if self.keywords:
            haystack = self.tail + piece.casefold()
            for keyword in self.keywords:
                if keyword in haystack:
                    return keyword
            self.tail = haystack[-self.keep:] if self.keep else ""
        if self.secrets:
            window = self.secret_tail + piece
            label = match_secret(window)
            if label:
                return label
            self.secret_tail = window[-_SECRET_TAIL:]
        return None


def clear_filter_cache() -> None:
    global _cache
    _cache = None


async def load_filter_rules() -> FilterRules:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    enabled = await keyword_filter_enabled()
    request_keywords: list[str] = []
    if enabled:
        rows = await SecurityKeyword.filter(is_enabled=True).only("keyword_key")
        request_keywords.extend(row.keyword_key for row in rows)
    rules = FilterRules(
        enabled,
        tuple(request_keywords),
        (),
        await secret_scan_enabled(),
    )
    _cache = (now, rules)
    return rules


def _add_text(parts: list[str], value: Any) -> None:
    if isinstance(value, str):
        if value:
            parts.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _add_text(parts, item)
        return
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        nested = value.get("content")
        if nested is not None and nested is not value:
            _add_text(parts, nested)
        tool_input = value.get("input")
        if isinstance(tool_input, (dict, list)):
            parts.append(json.dumps(tool_input, ensure_ascii=False, default=str))


def request_text(body: dict | None) -> str:
    """只取用户会发出去的内容，不扫描模型名和协议字段。"""
    if not body:
        return ""
    parts: list[str] = []
    _add_text(parts, body.get("system"))
    _add_text(parts, body.get("messages"))
    _add_text(parts, body.get("prompt"))
    _add_text(parts, body.get("input"))
    return "\n".join(parts)


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    if not text or not keywords:
        return None
    folded = text.casefold()
    for keyword in keywords:
        if keyword in folded:
            return keyword
    return None


_SECRET_LABELS = frozenset(name for name, _pattern in _SECRET_RULES)


def keyword_was_hit(security_hit: str) -> bool:
    """True when a keyword matched. Secret pattern names are not keywords."""
    return any(label and label not in _SECRET_LABELS for label in security_hit.split(","))


def remember_hit(hits: list[str], label: str | None) -> None:
    if label and label not in hits:
        hits.append(label)


def format_hits(hits: list[str] | None) -> str:
    if not hits:
        return ""
    return ",".join(hits)[:128]


async def collect_request_hits(body: dict | None, *, exempt: bool = False) -> list[str]:
    """命中只返回名称，调用方写日志，不中断请求。"""
    if exempt:
        return []
    rules = await load_filter_rules()
    text = request_text(body)
    hits: list[str] = []
    if rules.enabled:
        remember_hit(hits, _first_keyword(text, rules.request_keywords))
    if rules.secret_scan:
        remember_hit(hits, match_secret(text))
    return hits


async def collect_response_hits(response: Any, *, exempt: bool = False) -> list[str]:
    if exempt:
        return []
    rules = await load_filter_rules()
    if not rules.secret_scan:
        return []
    return [label] if (label := match_secret(response_visible_text(response))) else []


async def open_response_scanner(*, exempt: bool = False) -> ResponseScanner | None:
    if exempt:
        return None
    rules = await load_filter_rules()
    keywords = rules.response_keywords if rules.enabled else ()
    if not keywords and not rules.secret_scan:
        return None
    return ResponseScanner(keywords, rules.secret_scan)


def visible_sse_text(line: str) -> str:
    return sse_visible_text(line)
