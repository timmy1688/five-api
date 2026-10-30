import httpx

# The upstream rejected the platform's own key or account, never the customer's request.
CREDENTIAL_STATUSES = {401, 403}


class NoReadyUpstreamKey(Exception):
    """Every upstream key on the channel is cooling down; nothing was sent."""

    def __init__(self, channel_id: int):
        super().__init__(f"All upstream keys on channel {channel_id} are cooling down")


def upstream_status(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def is_retryable_error(exc: Exception) -> bool:
    """返回 True 表示该异常值得换一个渠道重试。"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    if isinstance(exc, httpx.RemoteProtocolError):
        return True
    return False


def is_credential_error(exc: Exception) -> bool:
    return upstream_status(exc) in CREDENTIAL_STATUSES


def should_switch_channel(exc: Exception) -> bool:
    return is_retryable_error(exc) or is_credential_error(exc) or isinstance(exc, NoReadyUpstreamKey)


def never_reached_upstream(exc: Exception) -> bool:
    """Safe to resend a non-idempotent request: the upstream did not start the work."""
    if isinstance(exc, (NoReadyUpstreamKey, httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return True
    status = upstream_status(exc)
    return status == 429 or status in CREDENTIAL_STATUSES
