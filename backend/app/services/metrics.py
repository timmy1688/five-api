"""Prometheus 指标定义和记录。"""

from prometheus_client import Counter, Gauge, Histogram

# 请求总数
REQUEST_COUNT = Counter(
    "five_requests_total",
    "Total API requests",
    ["model", "provider", "channel", "status_code", "endpoint"],
)

# Token 总数
TOKEN_COUNT = Counter(
    "five_tokens_total",
    "Total tokens processed",
    ["model", "type"],
)

# 费用总额
COST_TOTAL = Counter(
    "five_cost_total",
    "Total cost in USD",
    ["model"],
)

# 请求延迟
REQUEST_LATENCY = Histogram(
    "five_request_latency_seconds",
    "Request latency in seconds",
    ["model", "provider"],
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300],
)

# 活跃渠道和 Key 数
ACTIVE_CHANNELS = Gauge("five_active_channels", "Number of enabled channels")
ACTIVE_KEYS = Gauge("five_active_keys", "Number of enabled API keys")


def record_request_metrics(
    model: str,
    provider: str,
    channel_name: str,
    status_code: int,
    endpoint: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    cost: float,
    latency_seconds: float,
):
    """在请求完成后记录所有 Prometheus 指标。"""
    REQUEST_COUNT.labels(
        model=model, provider=provider, channel=channel_name,
        status_code=str(status_code), endpoint=endpoint,
    ).inc()

    if prompt_tokens > 0:
        TOKEN_COUNT.labels(model=model, type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        TOKEN_COUNT.labels(model=model, type="completion").inc(completion_tokens)
    if cached_tokens > 0:
        TOKEN_COUNT.labels(model=model, type="cached").inc(cached_tokens)

    if cost > 0:
        COST_TOTAL.labels(model=model).inc(cost)

    REQUEST_LATENCY.labels(model=model, provider=provider).observe(latency_seconds)
