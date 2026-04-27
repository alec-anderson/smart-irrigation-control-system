from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .collectors import (
    DemoCollector,
    LatestCsvLogCollector,
    LatestJsonFileCollector,
    NanoSerialCollector,
    SerialJsonCollector,
    TelemetryCollector,
)
from .config import Settings
from .db import LocalStore
from .sync import CloudSyncClient


@dataclass
class AlertState:
    zero_flow_started_at: float | None = None
    last_zero_flow_alert_at: float = 0.0
    last_vibration_alert_at: float = 0.0
    last_backlog_alert_at: float = 0.0


@dataclass
class UploadState:
    last_cloud_telemetry_at: float = 0.0
    last_drive_mode: str | None = None
    last_pump_on: bool | None = None
    last_limit_min_active: bool | None = None
    last_limit_max_active: bool | None = None


def choose_collector(settings: Settings, force_demo: bool) -> TelemetryCollector:
    if force_demo or settings.telemetry_source == "demo":
        return DemoCollector()
    if settings.telemetry_source == "file":
        return LatestJsonFileCollector(settings.telemetry_file)
    if settings.telemetry_source == "csv":
        return LatestCsvLogCollector(settings.control_csv_glob)
    if settings.telemetry_source != "serial":
        raise ValueError(f"unknown TELEMETRY_SOURCE: {settings.telemetry_source}")
    if not settings.serial_port:
        raise ValueError("SERIAL_PORT is required when TELEMETRY_SOURCE=serial")
    if settings.serial_protocol == "json":
        return SerialJsonCollector(settings.serial_port, settings.serial_baud)
    return NanoSerialCollector(settings.serial_port, settings.serial_baud)


def maybe_create_local_alerts(
    store: LocalStore,
    settings: Settings,
    telemetry: dict,
    state: AlertState,
) -> None:
    """Create monitoring-only alerts. These do not alter local control state."""
    now = time.monotonic()

    pump_on = bool(telemetry.get("pump_on"))
    flow_rate = float(telemetry.get("flow_rate_l_min") or 0.0)
    zero_flow_active = (
        settings.zero_flow_alert_enabled
        and pump_on
        and flow_rate < settings.zero_flow_threshold_l_min
    )
    if zero_flow_active:
        if state.zero_flow_started_at is None:
            state.zero_flow_started_at = now
        zero_flow_duration = now - state.zero_flow_started_at
        cooldown_elapsed = now - state.last_zero_flow_alert_at
        if (
            zero_flow_duration >= settings.zero_flow_min_seconds
            and cooldown_elapsed >= settings.zero_flow_cooldown_seconds
        ):
            store.insert_event(
                settings.device_id,
                severity="warning",
                event_type="zero_flow_while_irrigating",
                message="Pump is reported on but measured flow is near zero.",
                payload={
                    "flow_rate_l_min": flow_rate,
                    "duration_seconds": round(zero_flow_duration, 1),
                    "threshold_l_min": settings.zero_flow_threshold_l_min,
                },
            )
            state.last_zero_flow_alert_at = now
    else:
        state.zero_flow_started_at = None

    vibration = telemetry.get("vibration_rms_g")
    if (
        vibration is not None
        and float(vibration) > settings.vibration_alert_threshold_g
        and now - state.last_vibration_alert_at >= settings.vibration_alert_cooldown_seconds
    ):
        store.insert_event(
            settings.device_id,
            severity="warning",
            event_type="excessive_vibration",
            message="Vibration RMS exceeded prototype threshold.",
            payload={
                "vibration_rms_g": vibration,
                "threshold_g": settings.vibration_alert_threshold_g,
            },
        )
        state.last_vibration_alert_at = now

    backlog = store.backlog_count()
    if (
        backlog > settings.queue_backlog_alert_threshold
        and now - state.last_backlog_alert_at > 300
    ):
        store.insert_event(
            settings.device_id,
            severity="warning",
            event_type="cloud_sync_backlog",
            message="Cloud upload queue is growing while local logging continues.",
            payload={"backlog_count": backlog},
        )
        state.last_backlog_alert_at = now


def should_upload_telemetry(
    settings: Settings,
    telemetry: dict,
    state: UploadState,
) -> bool:
    """Upload lower-rate cloud telemetry while keeping all samples local."""
    now = time.monotonic()
    pump_on = bool(telemetry.get("pump_on"))
    limit_min_active = bool(telemetry.get("limit_min_active"))
    limit_max_active = bool(telemetry.get("limit_max_active"))
    drive_mode = telemetry.get("drive_mode")

    state_changed = (
        state.last_pump_on is not None
        and (
            pump_on != state.last_pump_on
            or limit_min_active != state.last_limit_min_active
            or limit_max_active != state.last_limit_max_active
            or drive_mode != state.last_drive_mode
        )
    )
    interval_elapsed = (
        now - state.last_cloud_telemetry_at
        >= settings.cloud_telemetry_min_interval_seconds
    )

    state.last_pump_on = pump_on
    state.last_limit_min_active = limit_min_active
    state.last_limit_max_active = limit_max_active
    state.last_drive_mode = drive_mode

    if state.last_cloud_telemetry_at == 0.0 or state_changed or interval_elapsed:
        state.last_cloud_telemetry_at = now
        return True
    return False


def run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    store = LocalStore(settings.sqlite_path)
    store.init_schema()
    collector = choose_collector(settings, force_demo=args.demo)
    sync_client = CloudSyncClient(
        api_url=settings.cloud_api_url,
        device_id=settings.device_id,
        device_token=settings.device_token,
        timeout_seconds=settings.sync_timeout_seconds,
    )

    stop_requested = False

    def _handle_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    last_sync_at = 0.0
    alert_state = AlertState()
    upload_state = UploadState()

    print(f"Logging to {Path(settings.sqlite_path).resolve()}")
    print(f"Uploading to {settings.cloud_api_url} as {settings.device_id}")

    try:
        while not stop_requested:
            telemetry = collector.read_telemetry()
            upload_telemetry = should_upload_telemetry(settings, telemetry, upload_state)
            store.insert_telemetry(settings.device_id, telemetry, enqueue=upload_telemetry)
            maybe_create_local_alerts(
                store, settings, telemetry, alert_state
            )
            store.upsert_device_status(
                settings.device_id,
                connection_state="local_online",
                current_mode=telemetry.get("drive_mode"),
                payload={
                    "last_sample_source": telemetry.get("source"),
                    "pump_on": telemetry.get("pump_on"),
                    "flow_rate_l_min": telemetry.get("flow_rate_l_min"),
                },
            )

            now = time.monotonic()
            if now - last_sync_at >= settings.sync_interval_seconds:
                result = sync_client.sync_once(store, settings.sync_batch_size)
                last_sync_at = now
                if result.error:
                    store.upsert_device_status(
                        settings.device_id,
                        connection_state="cloud_sync_error",
                        current_mode=telemetry.get("drive_mode"),
                        last_error=result.error,
                    )
                    print(f"sync failed: {result.error}")
                elif result.uploaded:
                    print(f"synced {result.uploaded}/{result.attempted} queued records")

            if args.once:
                break
            time.sleep(settings.sample_interval_seconds)
    finally:
        store.close()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pi telemetry logger and cloud sync worker")
    parser.add_argument("--demo", action="store_true", help="use synthetic telemetry")
    parser.add_argument("--once", action="store_true", help="collect one sample and exit")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
