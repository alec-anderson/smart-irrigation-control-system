from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(120), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    monotonic_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    soil_moisture_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    flow_rate_l_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    cumulative_flow_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    angle_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    alignment_error_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_min_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    limit_max_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pump_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    valve_position_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    drive_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    demo_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    encoder_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vibration_rms_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(120), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    severity: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DeviceStatus(Base):
    __tablename__ = "device_status"

    device_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connection_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pi_app_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sync_backlog_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class IrrigationRun(Base):
    __tablename__ = "irrigation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(120), index=True)
    run_type: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_flow_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
