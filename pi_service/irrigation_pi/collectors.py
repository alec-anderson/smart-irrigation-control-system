from __future__ import annotations

import csv
import glob
import json
import math
from pathlib import Path
import random
import time
from dataclasses import dataclass
from typing import Any, Protocol

DEMO_STATE_NAMES = {
    0: "IDLE",
    1: "OPEN",
    2: "PUMP",
    3: "VALVE",
    4: "DRIVE",
}


class TelemetryCollector(Protocol):
    def read_telemetry(self) -> dict[str, Any]:
        """Return one normalized telemetry sample."""


@dataclass
class DemoCollector:
    """Synthetic data source for end-to-end testing without hardware."""

    source: str = "demo"
    cumulative_flow_l: float = 0.0
    encoder_count: int = 0
    _sample_index: int = 0

    def read_telemetry(self) -> dict[str, Any]:
        self._sample_index += 1
        phase = self._sample_index / 20.0
        pump_on = (self._sample_index // 15) % 2 == 0
        flow_rate = max(0.0, 8.0 + 2.0 * math.sin(phase)) if pump_on else 0.0
        self.cumulative_flow_l += flow_rate / 30.0
        self.encoder_count += 12 if pump_on else 0
        angle = (180.0 + 45.0 * math.sin(phase / 2.0)) % 360.0

        return {
            "source": self.source,
            "soil_moisture_pct": round(33.0 + 6.0 * math.sin(phase / 3.0), 2),
            "flow_rate_l_min": round(flow_rate, 2),
            "cumulative_flow_l": round(self.cumulative_flow_l, 2),
            "angle_deg": round(angle, 2),
            "alignment_error_deg": round(abs(180.0 - angle), 2),
            "limit_min_active": False,
            "limit_max_active": angle > 220.0,
            "pump_on": pump_on,
            "valve_position_pct": 100.0 if pump_on else 0.0,
            "drive_mode": "auto_demo" if pump_on else "idle",
            "demo_mode": "synthetic",
            "encoder_count": self.encoder_count,
            "vibration_rms_g": round(0.04 + random.random() * 0.03, 3),
        }


class LatestJsonFileCollector:
    """
    Reads a telemetry snapshot written by the existing Pi control service.

    This is the preferred integration when the control service already owns the
    Nano serial line. The writer should replace the JSON file atomically so this
    reader never sees partial JSON.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_marker: tuple[int, int] | None = None

    def read_telemetry(self) -> dict[str, Any]:
        while True:
            try:
                stat = self.path.stat()
            except FileNotFoundError:
                time.sleep(0.5)
                continue

            marker = (stat.st_mtime_ns, stat.st_size)
            if marker == self._last_marker:
                time.sleep(0.2)
                continue

            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.1)
                continue

            if not isinstance(data, dict):
                raise ValueError(f"{self.path} must contain a JSON object")

            self._last_marker = marker
            return normalize_control_service_snapshot(data)


class LatestCsvLogCollector:
    """
    Reads the newest row from the existing control service CSV log.

    This avoids modifying the control service and avoids opening the Nano serial
    port from the cloud uploader.
    """

    def __init__(self, csv_glob: str) -> None:
        self.csv_glob = csv_glob
        self._last_marker: tuple[str, int, int] | None = None

    def read_telemetry(self) -> dict[str, Any]:
        while True:
            path = self._newest_log_path()
            if path is None:
                time.sleep(0.5)
                continue

            stat = path.stat()
            marker = (str(path), stat.st_mtime_ns, stat.st_size)
            if marker == self._last_marker:
                time.sleep(0.2)
                continue

            row = self._read_last_row(path)
            if row is None:
                time.sleep(0.2)
                continue

            self._last_marker = marker
            return normalize_control_service_snapshot(row)

    def _newest_log_path(self) -> Path | None:
        matches = [Path(path) for path in glob.glob(self.csv_glob)]
        if not matches:
            return None
        return max(matches, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _read_last_row(path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
        except (OSError, csv.Error):
            return None
        if not rows:
            return None
        return {key: _coerce_csv_value(value) for key, value in rows[-1].items()}


def _coerce_csv_value(value: str | None) -> Any:
    if value is None:
        return None
    clean = value.strip()
    if clean == "":
        return None
    try:
        as_int = int(clean)
        return as_int
    except ValueError:
        pass
    try:
        return float(clean)
    except ValueError:
        return clean


def normalize_control_service_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Map common local-control field names onto the cloud telemetry schema."""
    telemetry = dict(data)
    raw = dict(data)

    mappings = {
        "nano_angle_deg": "angle_deg",
        "nano_error_deg": "alignment_error_deg",
        "nano_lim1": "limit_min_active",
        "nano_lim2": "limit_max_active",
        "nano_pump": "pump_on",
        "nano_valve_pct": "valve_position_pct",
        "nano_mode": "drive_mode",
        "nano_demo_state": "demo_mode",
        "nano_motion_mode": "motion_mode",
        "flow_l_min": "flow_rate_l_min",
        "flow_lpm": "flow_rate_l_min",
        "total_flow_l": "cumulative_flow_l",
        "flow_total_liters": "cumulative_flow_l",
        "soil_pct": "soil_moisture_pct",
        "enc1_count": "encoder_count",
        "vib_std": "vibration_rms_g",
    }

    for source_key, target_key in mappings.items():
        if target_key not in telemetry and source_key in telemetry:
            telemetry[target_key] = telemetry[source_key]

    for bool_key in ("limit_min_active", "limit_max_active", "pump_on"):
        if bool_key in telemetry and telemetry[bool_key] is not None:
            telemetry[bool_key] = _as_bool(telemetry[bool_key])

    for float_key in (
        "soil_moisture_pct",
        "flow_rate_l_min",
        "cumulative_flow_l",
        "angle_deg",
        "alignment_error_deg",
        "valve_position_pct",
        "vibration_rms_g",
    ):
        if float_key in telemetry and telemetry[float_key] is not None:
            telemetry[float_key] = _as_float(telemetry[float_key])

    if "encoder_count" in telemetry and telemetry["encoder_count"] is not None:
        telemetry["encoder_count"] = _as_int(telemetry["encoder_count"])

    telemetry.setdefault("source", "control_service_file")
    telemetry["raw"] = raw
    return telemetry


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: str, none_if_negative: bool = False) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if none_if_negative and result < 0:
        return None
    return result


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(value: str) -> bool:
    return value.strip() == "1"


def parse_nano_line(line: str) -> dict[str, Any] | None:
    """
    Parse the existing Nano telemetry protocol without changing control logic.

    Supported inputs:
    - TEL,... CSV emitted by the current Arduino sketch.
    - ANGLE:...,LIM1:...,PUMP:... key/value status lines.

    ACK/ERR/STATUS lines are useful for the local console but are not telemetry
    samples, so this parser returns None for them.
    """
    clean = line.strip()
    if not clean:
        return None

    if clean.startswith("TEL,"):
        parts = clean.split(",")
        telemetry: dict[str, Any] = {
            "source": "nano_tel",
            "raw": {"line": clean, "parts": parts},
        }

        if len(parts) >= 12:
            telemetry["nano_millis"] = parts[1]
            telemetry["m1_cmd"] = _to_int(parts[2])
            telemetry["m2_cmd"] = _to_int(parts[3])
            telemetry["nano_enabled"] = _flag(parts[4])
            telemetry["angle_deg"] = _to_float(parts[5], none_if_negative=True)
            telemetry["limit_min_active"] = _flag(parts[6])
            telemetry["limit_max_active"] = _flag(parts[7])

        if len(parts) >= 23:
            drive_enabled = _flag(parts[12])
            direction = _to_int(parts[13])
            speed = _to_int(parts[14])
            target_angle = _to_float(parts[15], none_if_negative=True)
            error_deg = _to_float(parts[16])
            pump_on = _flag(parts[19])
            mode = parts[22].strip()

            telemetry.update(
                {
                    "drive_enabled": drive_enabled,
                    "direction": direction,
                    "speed": speed,
                    "target_angle_deg": target_angle,
                    "alignment_error_deg": error_deg,
                    "travel_cmd": _to_int(parts[17]),
                    "align_cmd": _to_int(parts[18]),
                    "pump_on": pump_on,
                    "pump_control_enabled": _flag(parts[20]),
                    "valve_position_pct": _to_float(parts[21]),
                    "drive_mode": mode or ("drive_on" if drive_enabled else "idle"),
                }
            )

        if len(parts) >= 26:
            demo_state_id = _to_int(parts[24])
            telemetry["demo_active"] = _flag(parts[23])
            telemetry["demo_mode"] = DEMO_STATE_NAMES.get(demo_state_id, str(demo_state_id))
            telemetry["demo_next_direction"] = _to_int(parts[25])

        if len(parts) >= 28:
            telemetry["motion_mode"] = parts[26].strip()
            telemetry["motion_phase"] = parts[27].strip()

        telemetry["raw"].update(
            {key: value for key, value in telemetry.items() if key not in {"raw"}}
        )
        return telemetry

    if clean.startswith("ANGLE:"):
        telemetry = {
            "source": "nano_status",
            "raw": {"line": clean},
        }
        for pair in clean.split(","):
            if ":" not in pair:
                continue
            key, value = pair.split(":", 1)
            key = key.strip().upper()
            value = value.strip()
            telemetry["raw"][key] = value

            if key == "ANGLE":
                telemetry["angle_deg"] = None if value == "N/A" else _to_float(value)
            elif key == "LIM1":
                telemetry["limit_min_active"] = _flag(value)
            elif key == "LIM2":
                telemetry["limit_max_active"] = _flag(value)
            elif key == "PUMP":
                telemetry["pump_on"] = _flag(value)
            elif key == "PCTRL":
                telemetry["pump_control_enabled"] = _flag(value)
            elif key == "VALVE":
                telemetry["valve_position_pct"] = _to_float(value)
            elif key == "DRIVE":
                telemetry["drive_enabled"] = _flag(value)
            elif key == "DIR":
                telemetry["direction"] = 1 if value == "FWD" else -1
            elif key == "SPEED":
                telemetry["speed"] = _to_int(value)
            elif key == "TARGET":
                telemetry["target_angle_deg"] = None if value == "N/A" else _to_float(value)
            elif key == "ERR":
                telemetry["alignment_error_deg"] = None if value == "N/A" else _to_float(value)
            elif key == "TRAVEL":
                telemetry["travel_cmd"] = _to_int(value)
            elif key == "ALIGN":
                telemetry["align_cmd"] = _to_int(value)
            elif key == "MODE":
                telemetry["drive_mode"] = value
            elif key == "MOTION":
                telemetry["motion_mode"] = value
            elif key == "MPHASE":
                telemetry["motion_phase"] = value
            elif key == "DEMO":
                telemetry["demo_mode"] = value
                telemetry["demo_active"] = value != "IDLE"
            elif key == "DEMONEXT":
                telemetry["demo_next_direction"] = 1 if value == "FWD" else -1

        if "drive_mode" not in telemetry and "drive_enabled" in telemetry:
            telemetry["drive_mode"] = "drive_on" if telemetry["drive_enabled"] else "idle"
        return telemetry

    return None


class NanoSerialCollector:
    """Reads the current Nano TEL/ANGLE serial protocol at 115200 baud."""

    def __init__(self, port: str, baud: int) -> None:
        import serial

        self._serial = serial.Serial(port=port, baudrate=baud, timeout=1)
        self._last_status_request_at = 0.0
        time.sleep(2.0)
        self._send_status_request()

    def _send_status_request(self) -> None:
        self._serial.write(b"STATUS\n")
        self._last_status_request_at = time.monotonic()

    def read_telemetry(self) -> dict[str, Any]:
        while True:
            if time.monotonic() - self._last_status_request_at > 5.0:
                self._send_status_request()

            line = self._serial.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue

            telemetry = parse_nano_line(line)
            if telemetry is None:
                continue
            return telemetry


class SerialJsonCollector:
    """
    Reads newline-delimited JSON telemetry from the Arduino/Pi serial bridge.

    Expected line shape can be flexible. Any fields already matching the
    telemetry schema pass through directly. Example:
    {"angle_deg": 92.1, "pump_on": true, "limit_min_active": false}
    """

    def __init__(self, port: str, baud: int) -> None:
        import serial

        self._serial = serial.Serial(port=port, baudrate=baud, timeout=2)

    def read_telemetry(self) -> dict[str, Any]:
        while True:
            line = self._serial.readline().decode("utf-8", errors="replace").strip()
            if not line:
                time.sleep(0.05)
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("serial telemetry line must decode to a JSON object")
            data.setdefault("source", "serial")
            data.setdefault("raw", dict(data))
            return data
