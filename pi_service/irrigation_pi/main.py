from __future__ import annotations

import argparse
import signal
import sys
import time
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
    last_backlog_alert_at: float,
) -> float:
    """Create monitoring-only alerts. These do not alter local control state."""
    now = time.monotonic()

    pump_on = bool(telemetry.get("pump_on"))
    flow_rate = float(telemetry.get("flow_rate_l_min") or 0.0)
    if pump_on and flow_rate < 0.1:
        store.insert_event(
            settings.device_id,
            severity="warning",
            event_type="zero_flow_while_irrigating",
            message="Pump is reported on but measured flow is near zero.",
            payload={"flow_rate_l_min": flow_rate},
        )

    vibration = telemetry.get("vibration_rms_g")
    if vibration is not None and float(vibration) > 0.5:
        store.insert_event(
            settings.device_id,
            severity="warning",
            event_type="excessive_vibration",
            message="Vibration RMS exceeded prototype threshold.",
            payload={"vibration_rms_g": vibration},
        )

    backlog = store.backlog_count()
    if (
        backlog > settings.queue_backlog_alert_threshold
        and now - last_backlog_alert_at > 300
    ):
        store.insert_event(
            settings.device_id,
            severity="warning",
            event_type="cloud_sync_backlog",
            message="Cloud upload queue is growing while local logging continues.",
            payload={"backlog_count": backlog},
        )
        return now

    return last_backlog_alert_at


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
    last_backlog_alert_at = 0.0

    print(f"Logging to {Path(settings.sqlite_path).resolve()}")
    print(f"Uploading to {settings.cloud_api_url} as {settings.device_id}")

    try:
        while not stop_requested:
            telemetry = collector.read_telemetry()
            store.insert_telemetry(settings.device_id, telemetry)
            last_backlog_alert_at = maybe_create_local_alerts(
                store, settings, telemetry, last_backlog_alert_at
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
