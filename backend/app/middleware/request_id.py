import re
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.request_context import client_request_id, credentials


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode(errors="ignore")
        supplied = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied) else ""
        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state.update(request_id=request_id, client_request_id=supplied)
        correlation = client_request_id.set(supplied)
        secrets = credentials.set(())

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                response_headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                response_headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            client_request_id.reset(correlation)
            credentials.reset(secrets)
