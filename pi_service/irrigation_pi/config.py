from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a local .env file without overriding the shell."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    device_id: str
    sqlite_path: Path
    cloud_api_url: str
    device_token: str
    sample_interval_seconds: float
    sync_interval_seconds: float
    sync_batch_size: int
    sync_timeout_seconds: float
    queue_backlog_alert_threshold: int
    cloud_telemetry_min_interval_seconds: float
    zero_flow_alert_enabled: bool
    zero_flow_threshold_l_min: float
    zero_flow_min_seconds: float
    zero_flow_cooldown_seconds: float
    vibration_alert_threshold_g: float
    vibration_alert_cooldown_seconds: float
    telemetry_source: str
    telemetry_file: Path
    control_csv_glob: str
    serial_port: str
    serial_baud: int
    serial_protocol: str

    @classmethod
    def load(cls) -> "Settings":
        load_env_file()
        return cls(
            device_id=os.getenv("DEVICE_ID", "pi-prototype-001"),
            sqlite_path=Path(os.getenv("SQLITE_PATH", "./data/irrigation_pi.sqlite3")),
            cloud_api_url=os.getenv("CLOUD_API_URL", "http://127.0.0.1:8000").rstrip("/"),
            device_token=os.getenv("DEVICE_TOKEN", "dev-device-token-change-me"),
            sample_interval_seconds=_get_float("SAMPLE_INTERVAL_SECONDS", 2.0),
            sync_interval_seconds=_get_float("SYNC_INTERVAL_SECONDS", 10.0),
            sync_batch_size=_get_int("SYNC_BATCH_SIZE", 100),
            sync_timeout_seconds=_get_float("SYNC_TIMEOUT_SECONDS", 5.0),
            queue_backlog_alert_threshold=_get_int("QUEUE_BACKLOG_ALERT_THRESHOLD", 1000),
            cloud_telemetry_min_interval_seconds=_get_float(
                "CLOUD_TELEMETRY_MIN_INTERVAL_SECONDS", 10.0
            ),
            zero_flow_alert_enabled=_get_bool("ZERO_FLOW_ALERT_ENABLED", True),
            zero_flow_threshold_l_min=_get_float("ZERO_FLOW_THRESHOLD_L_MIN", 0.1),
            zero_flow_min_seconds=_get_float("ZERO_FLOW_MIN_SECONDS", 15.0),
            zero_flow_cooldown_seconds=_get_float("ZERO_FLOW_COOLDOWN_SECONDS", 300.0),
            vibration_alert_threshold_g=_get_float("VIBRATION_ALERT_THRESHOLD_G", 0.5),
            vibration_alert_cooldown_seconds=_get_float(
                "VIBRATION_ALERT_COOLDOWN_SECONDS", 300.0
            ),
            telemetry_source=os.getenv("TELEMETRY_SOURCE", "demo").strip().lower(),
            telemetry_file=Path(os.getenv("TELEMETRY_FILE", "/var/lib/irrigation/latest_telemetry.json")),
            control_csv_glob=os.getenv(
                "CONTROL_CSV_GLOB",
                "/home/alec-anderson23/irrigation_production_nano_*.csv",
            ),
            serial_port=os.getenv("SERIAL_PORT", ""),
            serial_baud=_get_int("SERIAL_BAUD", 115200),
            serial_protocol=os.getenv("SERIAL_PROTOCOL", "nano_csv").strip().lower(),
        )
