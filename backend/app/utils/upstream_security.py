"""Require TLS for public upstreams while allowing local inference services."""
from ipaddress import ip_address
from urllib.parse import urlsplit

from app.config import settings


def validate_upstream_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("base_url must be an HTTP(S) URL")
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError("Invalid upstream URL") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname or port == 0:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("Put upstream credentials in api_key, not in base_url")
    host = parts.hostname.lower()
    internal = host == "localhost" or "." not in host or host.endswith((".test", ".internal", ".local", ".lan"))
    try:
        address = ip_address(host)
        internal = address.is_private or address.is_loopback
    except ValueError:
        pass
    if parts.scheme == "http" and not internal and not settings.ALLOW_INSECURE_UPSTREAMS:
        raise ValueError("Public upstreams require HTTPS")
    return value
