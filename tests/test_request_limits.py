from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from networksecurity.api.middleware import RequestBodyLimitMiddleware


def test_request_limit_rejects_streaming_body_without_content_length():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=8)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    def chunks():
        yield b"12345"
        yield b"67890"

    with TestClient(app) as client:
        response = client.post(
            "/echo",
            content=chunks(),
            headers={"Transfer-Encoding": "chunked"},
        )

    assert response.status_code == 413
    assert "8 byte limit" in response.json()["detail"]


def test_request_limit_allows_body_at_limit():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=8)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        response = client.post("/echo", content=b"12345678")

    assert response.status_code == 200
    assert response.json() == {"size": 8}
