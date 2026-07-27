from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence


@dataclass
class RecordEventInput:
    external_account_id: str
    event_type: str
    source: Optional[str] = None
    occurred_at: Optional[datetime] = None
    payload_json: Optional[str] = None
    payload: Optional[Mapping[str, Any]] = None
    idempotency_key: Optional[str] = None
    tenant_id: Optional[str] = None


@dataclass
class EventRecordResult:
    id: Optional[str]
    duplicate: bool


@dataclass
class BatchItemResult:
    index: int
    id: Optional[str]
    duplicate: bool
    error: Optional[str] = None


class ChurnWarnApiError(Exception):
    def __init__(self, status_code: int, message: str, body: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
