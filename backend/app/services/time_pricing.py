"""Time-of-day price multipliers, for vendors with peak and off-peak rates.

Rules are checked in order and the first match wins. A window whose end is
not after its start wraps past midnight. Times are local to the rule's UTC
offset, so a rule follows the vendor's clock rather than the server's.
"""

from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase

MAX_RULES = 50
MAX_MULTIPLIER = 10.0


def _minutes(value) -> int | None:
    try:
        hour, minute = str(value).strip().split(":")
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        return None
    if hour == 24 and minute == 0:
        return 1440
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalize_rules(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    rules: list[dict] = []
    for raw in value[:MAX_RULES]:
        if not isinstance(raw, dict):
            continue
        start, end = _minutes(raw.get("start")), _minutes(raw.get("end"))
        if start is None or end is None or start == end:
            continue
        try:
            multiplier = round(min(max(float(raw.get("multiplier", 1)), 0.0), MAX_MULTIPLIER), 4)
            offset = min(max(int(raw.get("utc_offset", 0)), -12), 14)
        except (TypeError, ValueError):
            continue
        models = raw.get("models") if isinstance(raw.get("models"), list) else []
        channel_ids = raw.get("channel_ids") if isinstance(raw.get("channel_ids"), list) else []
        rules.append({
            "name": " ".join(str(raw.get("name") or "").split())[:64] or f"{_clock(start)}-{_clock(end)}",
            "models": [m for m in (" ".join(str(x).split())[:64] for x in models) if m][:50],
            "channel_ids": sorted({int(c) for c in channel_ids if str(c).lstrip("-").isdigit()}),
            "start": _clock(start),
            "end": _clock(end),
            "utc_offset": offset,
            "multiplier": multiplier,
        })
    return rules


def _in_window(rule: dict, at: datetime) -> bool:
    local = at.astimezone(timezone(timedelta(hours=rule["utc_offset"])))
    now = local.hour * 60 + local.minute
    start, end = _minutes(rule["start"]), _minutes(rule["end"])
    if start < end:
        return start <= now < end
    return now >= start or now < end


def _model_matches(rule: dict, model: str) -> bool:
    return not rule["models"] or any(fnmatchcase(model, pattern) for pattern in rule["models"])


def match_rule(rules: list[dict], model: str, channel_id: int | None, at: datetime) -> dict | None:
    for rule in rules:
        if rule["channel_ids"] and channel_id not in rule["channel_ids"]:
            continue
        if _model_matches(rule, model) and _in_window(rule, at):
            return rule
    return None


def peak_multiplier(rules: list[dict], model: str, at: datetime) -> float:
    """Largest multiplier any channel could charge now, for pre-request holds."""
    matching = [
        rule["multiplier"] for rule in rules
        if _model_matches(rule, model) and _in_window(rule, at)
    ]
    return max([1.0, *matching])
