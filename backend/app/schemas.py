from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestRecord(BaseModel):
    client_queue_id: int | None = None
    entity_type: str = Field(..., examples=["telemetry", "event", "device_status", "irrigation_run"])
    entity_id: str
    operation: str = "upsert"
    payload: dict[str, Any]


class IngestBatch(BaseModel):
    device_id: str
    records: list[IngestRecord]


class IngestResponse(BaseModel):
    accepted: int
    accepted_client_queue_ids: list[int]
