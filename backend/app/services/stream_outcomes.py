"""Recognize native SSE failures and completion independently of HTTP status."""
import json

import httpx

from app.providers.base import ERROR_IN_OK

_ERROR_STATUSES = {
    "invalid_request_error": 400,
    "context_length_exceeded": 400,
    "authentication_error": 401,
    "invalid_api_key": 401,
    "permission_error": 403,
    "not_found_error": 404,
    "model_not_found": 404,
    "rate_limit_error": 429,
    "rate_limit_exceeded": 429,
    "insufficient_quota": 429,
    "server_is_overloaded": 503,
    "overloaded_error": 529,
}


class UpstreamStreamError(httpx.HTTPStatusError):
    """Reuse HTTP error classification while retaining the real upstream HTTP 200."""

    def __init__(self, error: dict, *, event: str = "", unfinished: bool = False, headers: dict | None = None):
        status = _ERROR_STATUSES.get(str(error.get("type")),
                                    _ERROR_STATUSES.get(str(error.get("code")), 502))
        request = httpx.Request("POST", "https://upstream.invalid")
        response = httpx.Response(status, json={"error": error}, headers=headers or {}, request=request,
                                  extensions={ERROR_IN_OK: True})
        super().__init__(str(error.get("message") or error.get("code") or "Upstream stream error"),
                         request=request, response=response)
        self.event = event
        self.unfinished = unfinished


class StreamOutcome:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.terminal = False
        self._choices: set[int] = set()
        self._finished_choices: set[int] = set()
        self._data: list[str] = []

    @property
    def finished(self) -> bool:
        # Some Chat-compatible upstreams close after finish_reason without [DONE].
        return self.terminal or bool(self._choices and self._choices <= self._finished_choices)

    def feed(self, chunk: str, headers: dict) -> UpstreamStreamError | None:
        for line in chunk.splitlines():
            if not line:
                self._data = []
                continue
            if not line.startswith("data:"):
                continue
            self._data.append(line[5:].removeprefix(" "))
            payload = "\n".join(self._data).strip()
            if payload == "[DONE]":
                if self.endpoint in {"/v1/chat/completions", "/v1/completions"}:
                    self.terminal = True
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            event_type = data.get("type")
            if event_type == "response.failed":
                response = data.get("response")
                error = response.get("error") if isinstance(response, dict) else None
                if not isinstance(error, dict):
                    error = {"type": "server_error", "message": "Upstream response failed"}
            elif event_type == "error" or isinstance(data.get("error"), (dict, str)):
                error = data.get("error")
                if not isinstance(error, dict):
                    error = {"type": "server_error", "code": data.get("code"),
                             "message": error or data.get("message") or "Upstream stream error"}
            else:
                error = None
            if error is not None:
                # Anthropic emits event/data/blank as separate chunks. Complete the
                # failing data event before the iterator is closed by the gateway.
                native_event = chunk.rstrip("\r\n") + "\n\n"
                return UpstreamStreamError(error, event=native_event, headers=headers)
            if self.endpoint == "/v1/messages":
                self.terminal = self.terminal or event_type == "message_stop"
            elif self.endpoint == "/v1/responses":
                self.terminal = self.terminal or event_type in {"response.completed", "response.incomplete"}
            elif self.endpoint in {"/v1/chat/completions", "/v1/completions"}:
                choices = data.get("choices")
                for index, choice in enumerate(choices if isinstance(choices, list) else []):
                    if not isinstance(choice, dict):
                        continue
                    choice_index = choice.get("index", index)
                    if not isinstance(choice_index, int):
                        continue
                    self._choices.add(choice_index)
                    if choice.get("finish_reason") is not None:
                        self._finished_choices.add(choice_index)
        return None

    def eof_error(self, headers: dict) -> UpstreamStreamError | None:
        if self.finished:
            return None
        return UpstreamStreamError(
            {"type": "server_error", "code": "stream_incomplete",
             "message": "Upstream stream ended before a terminal event"},
            unfinished=True, headers=headers,
        )
