import httpx


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
