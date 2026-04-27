from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
