from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import quote

import httpx

from churn_warn_sdk.accounts import ACCOUNT_BODY_UNSET, build_account_body
from churn_warn_sdk.models import (
    BatchItemResult,
    ChurnWarnApiError,
    EventRecordResult,
    RecordEventInput,
)
from churn_warn_sdk.privacy import redact_payload, redact_payload_json

_UNSET = ACCOUNT_BODY_UNSET

MAX_EVENTS_PER_BATCH = 500


def _normalize_token(token: str) -> str:
    t = token.strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len]


def _resolve_payload(inp: RecordEventInput, *, redact: bool = True) -> str:
    if inp.payload_json is not None and inp.payload_json != "":
        raw = inp.payload_json
        try:
            return redact_payload_json(raw) if redact else raw
        except Exception:
            return raw
    if inp.payload is None:
        return "{}"
    try:
        payload = redact_payload(inp.payload) if redact else dict(inp.payload)
        return json.dumps(payload, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _event_body(
    inp: RecordEventInput,
    *,
    default_source: str,
    include_tenant: bool,
    default_tenant_id: Optional[str],
    redact: bool = True,
) -> dict[str, Any]:
    src = (inp.source or default_source).strip()
    src = _truncate(src, 50)
    occurred = inp.occurred_at or datetime.now(timezone.utc)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    payload = _resolve_payload(inp, redact=redact)
    idem = inp.idempotency_key or uuid.uuid4().hex
    idem = _truncate(idem.strip(), 200)
    ext = _truncate(inp.external_account_id.strip(), 100)
    evt = _truncate(inp.event_type.strip(), 100)
    body: dict[str, Any] = {
        "externalAccountId": ext,
        "eventType": evt,
        "source": src,
        "occurredAt": occurred.isoformat(),
        "payload": payload,
        "idempotencyKey": idem,
    }
    if include_tenant:
        tid = inp.tenant_id or default_tenant_id
        if tid:
            body["tenantId"] = tid
    return body


def _resolve_batch_tenant(
    events: Sequence[RecordEventInput],
    default_tenant_id: Optional[str],
) -> Optional[str]:
    resolved: Optional[str] = None
    for e in events:
        if not e.tenant_id:
            continue
        if resolved is None:
            resolved = e.tenant_id
        elif resolved != e.tenant_id:
            raise ValueError(
                "All RecordEventInput.tenant_id values in a batch must be null or the same string."
            )
    return resolved or default_tenant_id


class ChurnWarnClient:
    """Async HTTP client; use as ``async with ChurnWarnClient(...) as c``."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        default_tenant_id: Optional[str] = None,
        default_source: str = "python_sdk",
        redact_payload: bool = True,
    ) -> None:
        self._base = base_url.rstrip("/") + "/"
        self._token = _normalize_token(token)
        self._default_tenant_id: Optional[str] = default_tenant_id
        self._default_source = default_source
        self._redact_payload = redact_payload
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> ChurnWarnClient:
        self._client = httpx.AsyncClient(
            base_url=self._base,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=httpx.Timeout(60.0),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use 'async with ChurnWarnClient(...) as client' before calling methods.")
        return self._client

    async def send_event(self, event: RecordEventInput) -> EventRecordResult:
        body = _event_body(
            event,
            default_source=self._default_source,
            include_tenant=True,
            default_tenant_id=self._default_tenant_id,
            redact=self._redact_payload,
        )
        r = await self._http().post("api/events", json=body)
        if r.status_code == 202:
            data = r.json()
            eid = data.get("id")
            return EventRecordResult(id=str(eid) if eid else None, duplicate=False)
        if r.status_code == 200:
            return EventRecordResult(id=None, duplicate=True)
        raise ChurnWarnApiError(r.status_code, r.reason_phrase or "", r.text)

    async def upsert_account(
        self,
        external_account_id: str,
        *,
        name: Any = _UNSET,
        email: Any = _UNSET,
        kind: Any = _UNSET,
        business_type: Any = _UNSET,
        monetary_value: Any = _UNSET,
        value_basis: Any = _UNSET,
        currency: Any = _UNSET,
        plan_key: Any = _UNSET,
        lifecycle_stage: Any = _UNSET,
        renewal_at: Any = _UNSET,
        status: Any = _UNSET,
        role: Any = _UNSET,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Upsert account facts via ``PUT /api/accounts/{externalId}``. Only fields you pass are written."""
        ext = (external_account_id or "").strip()
        if not ext:
            raise ValueError("external_account_id is required")
        if len(ext) > 100:
            ext = ext[:100]
        body = build_account_body(
            name=name,
            email=email,
            kind=kind,
            business_type=business_type,
            monetary_value=monetary_value,
            value_basis=value_basis,
            currency=currency,
            plan_key=plan_key,
            lifecycle_stage=lifecycle_stage,
            renewal_at=renewal_at,
            status=status,
            role=role,
            attributes=attributes,
        )
        r = await self._http().put(f"api/accounts/{quote(ext, safe='')}", json=body)
        if r.status_code < 200 or r.status_code >= 300:
            raise ChurnWarnApiError(r.status_code, r.reason_phrase or "", r.text)

    async def send_batch(self, events: Sequence[RecordEventInput]) -> list[BatchItemResult]:
        if not events:
            return []
        batch_tenant = _resolve_batch_tenant(events, self._default_tenant_id)
        merged: list[BatchItemResult] = []
        offset = 0
        for i in range(0, len(events), MAX_EVENTS_PER_BATCH):
            chunk = events[i : i + MAX_EVENTS_PER_BATCH]
            ev_bodies = [
                _event_body(
                    e,
                    default_source=self._default_source,
                    include_tenant=False,
                    default_tenant_id=self._default_tenant_id,
                    redact=self._redact_payload,
                )
                for e in chunk
            ]
            batch_body: dict[str, Any] = {"events": ev_bodies}
            if batch_tenant:
                batch_body["tenantId"] = batch_tenant
            r = await self._http().post("api/events/batch", json=batch_body)
            if r.status_code < 200 or r.status_code >= 300:
                raise ChurnWarnApiError(r.status_code, r.reason_phrase or "", r.text)
            data = r.json()
            rows = data.get("results") or []
            for row in rows:
                rid = row.get("id")
                merged.append(
                    BatchItemResult(
                        index=offset + int(row["index"]),
                        id=str(rid) if rid else None,
                        duplicate=bool(row.get("duplicate")),
                        error=row.get("error"),
                    )
                )
            offset += len(chunk)
        return merged
