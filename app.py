from __future__ import annotations

import os

import uvicorn

from networksecurity.api.app import create_app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        reload=False,
    )
