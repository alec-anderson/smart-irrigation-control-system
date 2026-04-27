from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .auth import require_dashboard_auth, require_device_auth
from .config import settings
from .database import Base, engine, get_db
from .models import DeviceStatus, Event, IrrigationRun, Telemetry
from .schemas import IngestBatch, IngestResponse, IngestRecord

app = FastAPI(title="Irrigation Monitoring API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Device-ID", "X-Device-Token"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if value:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return fallback or now_utc()


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def dt_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def telemetry_to_dict(row: Telemetry | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "device_id": row.device_id,
        "recorded_at": dt_iso(row.recorded_at),
        "received_at": dt_iso(row.received_at),
        "soil_moisture_pct": row.soil_moisture_pct,
        "flow_rate_l_min": row.flow_rate_l_min,
        "cumulative_flow_l": row.cumulative_flow_l,
        "angle_deg": row.angle_deg,
        "alignment_error_deg": row.alignment_error_deg,
        "limit_min_active": row.limit_min_active,
        "limit_max_active": row.limit_max_active,
        "pump_on": row.pump_on,
        "valve_position_pct": row.valve_position_pct,
        "drive_mode": row.drive_mode,
        "demo_mode": row.demo_mode,
        "encoder_count": row.encoder_count,
        "vibration_rms_g": row.vibration_rms_g,
    }


def event_to_dict(row: Event) -> dict[str, Any]:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "run_id": row.run_id,
        "recorded_at": dt_iso(row.recorded_at),
        "received_at": dt_iso(row.received_at),
        "severity": row.severity,
        "event_type": row.event_type,
        "message": row.message,
        "payload": row.payload or {},
    }


def status_to_dict(row: DeviceStatus | None) -> dict[str, Any] | None:
    if row is None:
        return None
    offline = False
    if row.last_seen_at:
        offline = now_utc() - row.last_seen_at.astimezone(timezone.utc) > timedelta(minutes=5)
    return {
        "device_id": row.device_id,
        "last_seen_at": dt_iso(row.last_seen_at),
        "last_recorded_at": dt_iso(row.last_recorded_at),
        "connection_state": "offline" if offline else row.connection_state,
        "sync_backlog_count": row.sync_backlog_count,
        "current_run_id": row.current_run_id,
        "current_mode": row.current_mode,
        "last_error": row.last_error,
        "updated_at": dt_iso(row.updated_at),
        "payload": row.payload or {},
    }


def run_to_dict(row: IrrigationRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "device_id": row.device_id,
        "run_type": row.run_type,
        "mode": row.mode,
        "started_at": dt_iso(row.started_at),
        "ended_at": dt_iso(row.ended_at),
        "start_reason": row.start_reason,
        "end_reason": row.end_reason,
        "total_flow_l": row.total_flow_l,
        "summary": row.summary or {},
    }


def upsert_status_from_record(
    db: Session,
    device_id: str,
    recorded_at: datetime,
    connection_state: str = "cloud_seen",
    current_mode: str | None = None,
    sync_backlog_count: int | None = None,
    last_error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    status = db.get(DeviceStatus, device_id)
    if status is None:
        status = DeviceStatus(device_id=device_id, updated_at=now_utc())
        db.add(status)
        # Make the pending status row visible to later records in the same batch.
        db.flush()
    status.last_seen_at = now_utc()
    status.last_recorded_at = recorded_at
    status.connection_state = connection_state
    status.current_mode = current_mode if current_mode is not None else status.current_mode
    status.sync_backlog_count = sync_backlog_count
    status.last_error = last_error
    status.payload = payload if payload is not None else status.payload
    status.updated_at = now_utc()


def ingest_telemetry(db: Session, device_id: str, record: IngestRecord) -> None:
    payload = record.payload
    record_id = str(payload.get("id") or record.entity_id)
    if db.get(Telemetry, record_id):
        return

    recorded_at = parse_dt(payload.get("recorded_at"))
    telemetry = Telemetry(
        id=record_id,
        device_id=device_id,
        recorded_at=recorded_at,
        received_at=now_utc(),
        monotonic_ms=payload.get("monotonic_ms"),
        source=payload.get("source"),
        soil_moisture_pct=payload.get("soil_moisture_pct"),
        flow_rate_l_min=payload.get("flow_rate_l_min"),
        cumulative_flow_l=payload.get("cumulative_flow_l"),
        angle_deg=payload.get("angle_deg"),
        alignment_error_deg=payload.get("alignment_error_deg"),
        limit_min_active=as_bool(payload.get("limit_min_active")),
        limit_max_active=as_bool(payload.get("limit_max_active")),
        pump_on=as_bool(payload.get("pump_on")),
        valve_position_pct=payload.get("valve_position_pct"),
        drive_mode=payload.get("drive_mode"),
        demo_mode=payload.get("demo_mode"),
        encoder_count=payload.get("encoder_count"),
        vibration_rms_g=payload.get("vibration_rms_g"),
        raw=payload.get("raw") or payload,
    )
    db.add(telemetry)
    upsert_status_from_record(
        db,
        device_id=device_id,
        recorded_at=recorded_at,
        current_mode=payload.get("drive_mode"),
        payload={
            "pump_on": payload.get("pump_on"),
            "flow_rate_l_min": payload.get("flow_rate_l_min"),
            "source": payload.get("source"),
        },
    )


def ingest_event(db: Session, device_id: str, record: IngestRecord) -> None:
    payload = record.payload
    record_id = str(payload.get("id") or record.entity_id)
    if db.get(Event, record_id):
        return
    event = Event(
        id=record_id,
        device_id=device_id,
        run_id=payload.get("run_id"),
        recorded_at=parse_dt(payload.get("recorded_at")),
        received_at=now_utc(),
        severity=payload.get("severity", "info"),
        event_type=payload.get("event_type", "event"),
        message=payload.get("message", ""),
        payload=payload.get("payload") or {},
    )
    db.add(event)


def ingest_device_status(db: Session, device_id: str, record: IngestRecord) -> None:
    payload = record.payload
    upsert_status_from_record(
        db,
        device_id=device_id,
        recorded_at=parse_dt(payload.get("recorded_at")),
        connection_state=payload.get("connection_state", "cloud_seen"),
        current_mode=payload.get("current_mode"),
        sync_backlog_count=payload.get("sync_backlog_count"),
        last_error=payload.get("last_error"),
        payload=payload.get("payload") or {},
    )


def ingest_run(db: Session, device_id: str, record: IngestRecord) -> None:
    payload = record.payload
    record_id = str(payload.get("id") or record.entity_id)
    run = db.get(IrrigationRun, record_id)
    if run is None:
        run = IrrigationRun(
            id=record_id,
            device_id=device_id,
            run_type=payload.get("run_type", "demo"),
            started_at=parse_dt(payload.get("started_at")),
            updated_at=now_utc(),
        )
        db.add(run)
    run.mode = payload.get("mode")
    run.ended_at = parse_dt(payload.get("ended_at"), fallback=None) if payload.get("ended_at") else None
    run.start_reason = payload.get("start_reason")
    run.end_reason = payload.get("end_reason")
    run.total_flow_l = payload.get("total_flow_l")
    run.summary = payload.get("summary") or {}
    run.updated_at = now_utc()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/ingest/batch", response_model=IngestResponse)
def ingest_batch(
    batch: IngestBatch,
    db: Session = Depends(get_db),
    authenticated_device_id: str = Depends(require_device_auth),
) -> IngestResponse:
    if batch.device_id != authenticated_device_id:
        raise HTTPException(status_code=403, detail="device ID mismatch")

    accepted_queue_ids: list[int] = []
    handlers = {
        "telemetry": ingest_telemetry,
        "event": ingest_event,
        "device_status": ingest_device_status,
        "irrigation_run": ingest_run,
    }

    for record in batch.records:
        handler = handlers.get(record.entity_type)
        if handler is None:
            raise HTTPException(status_code=400, detail=f"unknown entity_type: {record.entity_type}")
        handler(db, authenticated_device_id, record)
        if record.client_queue_id is not None:
            accepted_queue_ids.append(record.client_queue_id)

    db.commit()
    return IngestResponse(
        accepted=len(batch.records),
        accepted_client_queue_ids=accepted_queue_ids,
    )


@app.get("/v1/dashboard/devices", dependencies=[Depends(require_dashboard_auth)])
def list_devices(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.scalars(select(DeviceStatus).order_by(DeviceStatus.device_id)).all()
    return {"devices": [status_to_dict(row) for row in rows]}


@app.get("/v1/dashboard/devices/{device_id}/current", dependencies=[Depends(require_dashboard_auth)])
def current_device(device_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    status = db.get(DeviceStatus, device_id)
    telemetry = db.scalars(
        select(Telemetry)
        .where(Telemetry.device_id == device_id)
        .order_by(desc(Telemetry.recorded_at))
        .limit(1)
    ).first()
    events = db.scalars(
        select(Event)
        .where(Event.device_id == device_id)
        .order_by(desc(Event.recorded_at))
        .limit(10)
    ).all()
    return {
        "device_id": device_id,
        "status": status_to_dict(status),
        "telemetry": telemetry_to_dict(telemetry),
        "recent_events": [event_to_dict(row) for row in events],
    }


@app.get("/v1/dashboard/devices/{device_id}/telemetry", dependencies=[Depends(require_dashboard_auth)])
def telemetry_history(
    device_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=300, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    since = now_utc() - timedelta(hours=hours)
    rows = db.scalars(
        select(Telemetry)
        .where(Telemetry.device_id == device_id, Telemetry.recorded_at >= since)
        .order_by(desc(Telemetry.recorded_at))
        .limit(limit)
    ).all()
    rows = list(reversed(rows))
    return {"device_id": device_id, "telemetry": [telemetry_to_dict(row) for row in rows]}


@app.get("/v1/dashboard/devices/{device_id}/events", dependencies=[Depends(require_dashboard_auth)])
def recent_events(
    device_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.scalars(
        select(Event)
        .where(Event.device_id == device_id)
        .order_by(desc(Event.recorded_at))
        .limit(limit)
    ).all()
    return {"device_id": device_id, "events": [event_to_dict(row) for row in rows]}


@app.get("/v1/dashboard/devices/{device_id}/runs", dependencies=[Depends(require_dashboard_auth)])
def recent_runs(
    device_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.scalars(
        select(IrrigationRun)
        .where(IrrigationRun.device_id == device_id)
        .order_by(desc(IrrigationRun.started_at))
        .limit(limit)
    ).all()
    return {"device_id": device_id, "runs": [run_to_dict(row) for row in rows]}
