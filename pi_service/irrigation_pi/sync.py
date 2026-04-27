from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from .db import LocalStore


@dataclass
class SyncResult:
    attempted: int
    uploaded: int
    error: str | None = None


class CloudSyncClient:
    def __init__(
        self,
        api_url: str,
        device_id: str,
        device_token: str,
        timeout_seconds: float,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.device_id = device_id
        self.device_token = device_token
        self.timeout_seconds = timeout_seconds

    def sync_once(self, store: LocalStore, batch_size: int) -> SyncResult:
        rows = store.get_pending_queue(batch_size)
        if not rows:
            return SyncResult(attempted=0, uploaded=0)

        queue_ids = [int(row["id"]) for row in rows]
        records: list[dict[str, Any]] = []
        for row in rows:
            records.append(
                {
                    "client_queue_id": int(row["id"]),
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "operation": row["operation"],
                    "payload": json.loads(row["payload_json"]),
                }
            )

        try:
            response = requests.post(
                f"{self.api_url}/v1/ingest/batch",
                headers={
                    "X-Device-ID": self.device_id,
                    "X-Device-Token": self.device_token,
                },
                json={"device_id": self.device_id, "records": records},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            accepted_ids = [int(value) for value in body.get("accepted_client_queue_ids", [])]
            if not accepted_ids:
                accepted_ids = queue_ids
            store.mark_uploaded(accepted_ids)
            return SyncResult(attempted=len(queue_ids), uploaded=len(accepted_ids))
        except Exception as exc:
            store.mark_failed(queue_ids, str(exc))
            return SyncResult(attempted=len(queue_ids), uploaded=0, error=str(exc))
