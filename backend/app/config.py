from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_device_tokens(raw: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        device_id, token = item.split(":", 1)
        tokens[device_id.strip()] = token.strip()
    return tokens


@dataclass(frozen=True)
class Settings:
    database_url: str
    device_tokens: dict[str, str]
    dashboard_token: str
    cors_origins: list[str]

    @classmethod
    def load(cls) -> "Settings":
        load_env_file()
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./irrigation_backend_dev.sqlite3"),
            device_tokens=_parse_device_tokens(
                os.getenv("DEVICE_TOKENS", "pi-prototype-001:dev-device-token-change-me")
            ),
            dashboard_token=os.getenv("DASHBOARD_TOKEN", "dev-dashboard-token-change-me"),
            cors_origins=[
                origin.strip()
                for origin in os.getenv(
                    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
                ).split(",")
                if origin.strip()
            ],
        )


settings = Settings.load()
