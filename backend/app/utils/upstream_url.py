def upstream_url(base_url: str, path: str) -> str:
    """Join an API path without duplicating a compatible API prefix."""
    base = base_url.rstrip("/")
    normalized_path = "/" + path.lstrip("/")
    if normalized_path.startswith("/v1/") and base.lower().endswith(
        ("/v1", "/v1beta/openai", "/compatible-mode/v1")
    ):
        normalized_path = normalized_path[3:]
    return f"{base}{normalized_path}"
