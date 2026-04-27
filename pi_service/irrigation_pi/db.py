from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _json_dumps(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


class LocalStore:
    def __init__(self, db_path: Path, schema_path: Path | None = None) -> None:
        self.db_path = db_path
        self.schema_path = schema_path or Path(__file__).resolve().parents[1] / "schema.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("pragma foreign_keys = on")
        self._conn.execute("pragma journal_mode = wal")

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(self.schema_path.read_text(encoding="utf-8"))
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterable[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def insert_telemetry(self, device_id: str, payload: dict[str, Any]) -> str:
        record = dict(payload)
        record.setdefault("id", str(uuid.uuid4()))
        record.setdefault("device_id", device_id)
        record.setdefault("recorded_at", utc_now_iso())
        record.setdefault("monotonic_ms", monotonic_ms())
        record.setdefault("source", "pi")
        record["raw"] = payload.get("raw", payload)
        now = utc_now_iso()

        with self.transaction() as conn:
            conn.execute(
                """
                insert or ignore into telemetry (
                  id, device_id, recorded_at, monotonic_ms, source,
                  soil_moisture_pct, flow_rate_l_min, cumulative_flow_l,
                  angle_deg, alignment_error_deg, limit_min_active,
                  limit_max_active, pump_on, valve_position_pct, drive_mode,
                  demo_mode, encoder_count, vibration_rms_g, raw_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["device_id"],
                    record["recorded_at"],
                    record.get("monotonic_ms"),
                    record.get("source", "pi"),
                    record.get("soil_moisture_pct"),
                    record.get("flow_rate_l_min"),
                    record.get("cumulative_flow_l"),
                    record.get("angle_deg"),
                    record.get("alignment_error_deg"),
                    _bool_int(record.get("limit_min_active")),
                    _bool_int(record.get("limit_max_active")),
                    _bool_int(record.get("pump_on")),
                    record.get("valve_position_pct"),
                    record.get("drive_mode"),
                    record.get("demo_mode"),
                    record.get("encoder_count"),
                    record.get("vibration_rms_g"),
                    _json_dumps(record.get("raw")),
                    now,
                ),
            )
            self._enqueue(conn, "telemetry", record["id"], record)
        return record["id"]

    def insert_event(
        self,
        device_id: str,
        severity: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        record = {
            "id": str(uuid.uuid4()),
            "device_id": device_id,
            "run_id": run_id,
            "recorded_at": utc_now_iso(),
            "severity": severity,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        now = utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                insert into events (
                  id, device_id, run_id, recorded_at, severity, event_type,
                  message, payload_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    device_id,
                    run_id,
                    record["recorded_at"],
                    severity,
                    event_type,
                    message,
                    _json_dumps(record["payload"]),
                    now,
                ),
            )
            self._enqueue(conn, "event", record["id"], record)
        return record["id"]

    def upsert_device_status(
        self,
        device_id: str,
        connection_state: str,
        current_mode: str | None = None,
        last_error: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        backlog_count = self.backlog_count()
        recorded_at = utc_now_iso()
        record = {
            "device_id": device_id,
            "recorded_at": recorded_at,
            "connection_state": connection_state,
            "sync_backlog_count": backlog_count,
            "current_mode": current_mode,
            "last_error": last_error,
            "payload": payload or {},
        }

        with self.transaction() as conn:
            conn.execute(
                """
                insert into device_status (
                  device_id, recorded_at, connection_state, sync_backlog_count,
                  current_mode, last_error, payload_json, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(device_id) do update set
                  recorded_at = excluded.recorded_at,
                  connection_state = excluded.connection_state,
                  sync_backlog_count = excluded.sync_backlog_count,
                  current_mode = excluded.current_mode,
                  last_error = excluded.last_error,
                  payload_json = excluded.payload_json,
                  updated_at = excluded.updated_at,
                  synced_at = null
                """,
                (
                    device_id,
                    recorded_at,
                    connection_state,
                    backlog_count,
                    current_mode,
                    last_error,
                    _json_dumps(record["payload"]),
                    recorded_at,
                ),
            )
            self._enqueue(conn, "device_status", device_id, record)

    def upsert_run(self, device_id: str, run: dict[str, Any]) -> str:
        record = dict(run)
        record.setdefault("id", str(uuid.uuid4()))
        record.setdefault("device_id", device_id)
        record.setdefault("started_at", utc_now_iso())
        record.setdefault("run_type", "demo")
        now = utc_now_iso()

        with self.transaction() as conn:
            conn.execute(
                """
                insert into irrigation_runs (
                  id, device_id, run_type, mode, started_at, ended_at,
                  start_reason, end_reason, total_flow_l, summary_json,
                  created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  mode = excluded.mode,
                  ended_at = excluded.ended_at,
                  end_reason = excluded.end_reason,
                  total_flow_l = excluded.total_flow_l,
                  summary_json = excluded.summary_json,
                  updated_at = excluded.updated_at,
                  synced_at = null
                """,
                (
                    record["id"],
                    device_id,
                    record["run_type"],
                    record.get("mode"),
                    record["started_at"],
                    record.get("ended_at"),
                    record.get("start_reason"),
                    record.get("end_reason"),
                    record.get("total_flow_l"),
                    _json_dumps(record.get("summary")),
                    now,
                    now,
                ),
            )
            self._enqueue(conn, "irrigation_run", record["id"], record)
        return record["id"]

    def _enqueue(
        self,
        conn: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        operation: str = "upsert",
    ) -> None:
        now = utc_now_iso()
        conn.execute(
            """
            insert into upload_queue (
              entity_type, entity_id, operation, payload_json, status, created_at
            ) values (?, ?, ?, ?, 'pending', ?)
            on conflict(entity_type, entity_id, operation) do update set
              payload_json = excluded.payload_json,
              status = case
                when upload_queue.status = 'uploaded' then 'pending'
                else upload_queue.status
              end,
              next_attempt_at = null,
              last_error = null
            """,
            (entity_type, entity_id, operation, _json_dumps(payload), now),
        )

    def get_pending_queue(self, limit: int) -> list[sqlite3.Row]:
        now = utc_now_iso()
        rows = self._conn.execute(
            """
            select id, entity_type, entity_id, operation, payload_json, attempts
            from upload_queue
            where status in ('pending', 'retry')
              and (next_attempt_at is null or next_attempt_at <= ?)
            order by id asc
            limit ?
            """,
            (now, limit),
        ).fetchall()
        return list(rows)

    def mark_uploaded(self, queue_ids: list[int]) -> None:
        if not queue_ids:
            return
        now = utc_now_iso()
        placeholders = ",".join("?" for _ in queue_ids)
        with self.transaction() as conn:
            conn.execute(
                f"""
                update upload_queue
                set status = 'uploaded', uploaded_at = ?, last_error = null
                where id in ({placeholders})
                """,
                [now, *queue_ids],
            )

    def mark_failed(self, queue_ids: list[int], error: str) -> None:
        if not queue_ids:
            return
        now = datetime.now(timezone.utc)
        next_attempt = (now + timedelta(seconds=60)).isoformat()
        clipped_error = error[:500]
        placeholders = ",".join("?" for _ in queue_ids)
        with self.transaction() as conn:
            conn.execute(
                f"""
                update upload_queue
                set
                  status = case when attempts >= 10 then 'failed' else 'retry' end,
                  attempts = attempts + 1,
                  next_attempt_at = ?,
                  last_error = ?
                where id in ({placeholders})
                """,
                [next_attempt, clipped_error, *queue_ids],
            )

    def backlog_count(self) -> int:
        row = self._conn.execute(
            """
            select count(*) as count
            from upload_queue
            where status in ('pending', 'retry')
            """
        ).fetchone()
        return int(row["count"])
