import uuid
import re

from starlette.types import ASGIApp, Receive, Scope, Send


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode(errors="ignore")
        request_id = (
            supplied
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,36}", supplied)
            else str(uuid.uuid4())
        )
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
