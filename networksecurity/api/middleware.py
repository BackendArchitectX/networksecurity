from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PayloadTooLargeError(RuntimeError):
    pass


class RequestBodyLimitMiddleware:
    """Enforce body limits even when Content-Length is absent or untrusted.

    Edge proxies should enforce their own limit as well, but application correctness
    must not depend on clients honestly providing Content-Length. The receive wrapper
    counts decoded HTTP request bytes and aborts before FastAPI parses an oversized
    body.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._reject(scope, receive, send)
            return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise PayloadTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except PayloadTooLargeError:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": f"request exceeds {self.max_bytes} byte limit"},
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            length = int(value)
        except ValueError:
            return None
        return max(length, 0)
    return None
