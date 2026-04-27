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


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str
    device_tokens: dict[str, str]
    dashboard_token: str
    cors_origins: list[str]
    telemetry_retention_days: int
    event_retention_days: int
    retention_cleanup_interval_seconds: int

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
            telemetry_retention_days=_get_int("TELEMETRY_RETENTION_DAYS", 14),
            event_retention_days=_get_int("EVENT_RETENTION_DAYS", 30),
            retention_cleanup_interval_seconds=_get_int(
                "RETENTION_CLEANUP_INTERVAL_SECONDS", 3600
            ),
        )


settings = Settings.load()
