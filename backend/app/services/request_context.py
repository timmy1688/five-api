from contextvars import ContextVar

client_request_id: ContextVar[str] = ContextVar("client_request_id", default="")
credentials: ContextVar[tuple[str, ...]] = ContextVar("request_credentials", default=())


def remember_credential(value: str) -> None:
    if value and len(value) >= 4 and value not in credentials.get():
        credentials.set((*credentials.get(), value))
