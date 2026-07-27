"""ChurnWarn capture SDK: in-process queue and background batched posts to the gateway."""

from __future__ import annotations

import json
import queue as queue_lib
import random
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import httpx

from churn_warn_sdk.accounts import ACCOUNT_BODY_UNSET, build_account_body
from churn_warn_sdk.models import ChurnWarnApiError, RecordEventInput
from churn_warn_sdk.privacy import redact_payload, redact_payload_json

_UNSET = ACCOUNT_BODY_UNSET

MAX_EVENTS_PER_BATCH = 500

_SENTINEL = object()


def _safe_report_error(cb: Optional[Callable[[Exception], None]], err: Exception) -> None:
    """Invoke a user error callback without ever letting it throw back into the SDK."""
    if cb is None:
        return
    try:
        cb(err)
    except Exception:
        # A faulty error callback must never fault the background thread or the host.
        pass


@dataclass(frozen=True)
class ChurnWarnOptions:
    base_url: str
    api_key: Optional[str] = None
    api_token: Optional[str] = None
    default_tenant_id: Optional[str] = None
    default_source: str = "python_sdk"
    batch_size: int = 50
    flush_interval_seconds: float = 5.0
    max_queue_size: int = 10_000
    on_send_error: Optional[Callable[[Exception], None]] = None
    redact_payload: bool = True
    on_before_enqueue: Optional[Callable[[RecordEventInput], RecordEventInput]] = None
    # Retry attempts for a failed batch flush after the first try (0 disables). Only transient
    # failures are retried: network/timeout errors and HTTP 429/5xx. Batches are idempotent
    # (per-event idempotency_key), so retries never duplicate events server-side.
    max_retries: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 30.0


def _normalize_bearer(token: str) -> str:
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


def _single_body(
    inp: RecordEventInput,
    *,
    default_src: str,
    default_tid: Optional[str],
    include_tenant: bool,
    redact: bool = True,
) -> dict[str, Any]:
    src = (inp.source or default_src).strip()
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
        tid = inp.tenant_id or default_tid
        if tid:
            body["tenantId"] = tid
    return body


def _batch_tenant(records: list[RecordEventInput], default_tid: Optional[str]) -> Optional[str]:
    resolved: Optional[str] = None
    for e in records:
        if not e.tenant_id:
            continue
        if resolved is None:
            resolved = e.tenant_id
        elif resolved != e.tenant_id:
            raise ValueError("All tenant_id values in one batch must match")
    return resolved or default_tid


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _compute_backoff_seconds(attempt: int, base: float, cap: float) -> float:
    base = base if base > 0 else 0.5
    cap = cap if cap > 0 else 30.0
    capped = min(cap, base * (2 ** (attempt - 1)))
    # Equal jitter: half fixed, half random.
    return capped / 2 + random.random() * (capped / 2)


def _post_batch_with_retry(
    client: httpx.Client, batch_body: dict[str, Any], opts: ChurnWarnOptions
) -> None:
    """POST one batch body, retrying transient failures (network/timeout, HTTP 429/5xx) with
    exponential backoff + jitter. Runs on the background sender thread, so blocking sleeps are
    fine. Batches are idempotent (per-event idempotency_key), so retries never duplicate events.
    """
    max_retries = max(0, opts.max_retries)
    attempt = 0
    while True:
        try:
            r = client.post("api/events/batch", json=batch_body)
            if 200 <= r.status_code < 300:
                return
            if attempt < max_retries and _is_retryable_status(r.status_code):
                time.sleep(
                    _compute_backoff_seconds(
                        attempt + 1, opts.retry_base_delay_seconds, opts.retry_max_delay_seconds
                    )
                )
                attempt += 1
                continue
            raise ChurnWarnApiError(r.status_code, r.reason_phrase or "", r.text)
        except httpx.RequestError:
            # network/timeout error — retry while attempts remain, otherwise surface it
            if attempt < max_retries:
                time.sleep(
                    _compute_backoff_seconds(
                        attempt + 1, opts.retry_base_delay_seconds, opts.retry_max_delay_seconds
                    )
                )
                attempt += 1
                continue
            raise


def _post_events_batch(
    client: httpx.Client,
    records: list[RecordEventInput],
    opts: ChurnWarnOptions,
) -> None:
    """POST ``records`` to ``api/events/batch``, splitting at :data:`MAX_EVENTS_PER_BATCH` per request.

    Redaction runs here, in the background flush thread, not on the caller's thread.
    Per-event serialization errors are caught so one bad payload cannot drop the whole batch.
    """
    for i in range(0, len(records), MAX_EVENTS_PER_BATCH):
        chunk = records[i : i + MAX_EVENTS_PER_BATCH]
        btid = _batch_tenant(chunk, opts.default_tenant_id)
        events: list[dict[str, Any]] = []
        for e in chunk:
            try:
                events.append(
                    _single_body(
                        e,
                        default_src=opts.default_source,
                        default_tid=opts.default_tenant_id,
                        include_tenant=False,
                        redact=opts.redact_payload,
                    )
                )
            except Exception as ex:
                _safe_report_error(opts.on_send_error, ex)
        batch_body: dict[str, Any] = {"events": events}
        if btid:
            batch_body["tenantId"] = btid
        _post_batch_with_retry(client, batch_body, opts)


def _flush_pending_batches(
    pending: deque[RecordEventInput],
    client: httpx.Client,
    opts: ChurnWarnOptions,
    preferred_batch_size: int,
) -> None:
    """Take up to ``preferred_batch_size`` records at a time from ``pending`` and POST them.

    After a successful POST, if that chunk was smaller than ``preferred_batch_size`` (tail of
    the buffer), this round is done. On HTTP or transport failure, ``on_send_error`` runs and
    flushing stops for this call; remaining records stay in ``pending``.
    """
    while True:
        if not pending:
            return
        chunk: list[RecordEventInput] = []
        while len(chunk) < preferred_batch_size and pending:
            chunk.append(pending.popleft())
        if not chunk:
            return
        try:
            _post_events_batch(client, chunk, opts)
        except Exception as ex:
            _safe_report_error(opts.on_send_error, ex)
            break
        if len(chunk) < preferred_batch_size:
            return


_stop = threading.Event()

# Guards initialize()/shutdown() against each other (reentrant: initialize() calls shutdown()).
_lifecycle_lock = threading.RLock()

_thread: Optional[threading.Thread] = None
_event_q: Optional[queue_lib.Queue[Any]] = None
_http: Optional[httpx.Client] = None
_opts: Optional[ChurnWarnOptions] = None
_preferred_batch_size = 50
_idle_flush_seconds = 5.0


def _background_sender_loop() -> None:
    global _http, _opts
    assert _event_q is not None and _http is not None and _opts is not None
    client = _http
    options = _opts
    pending: deque[RecordEventInput] = deque()
    batch_size = _preferred_batch_size
    idle_flush = _idle_flush_seconds

    while not _stop.is_set() or not _event_q.empty() or pending:
        # Each iteration is wrapped so no unexpected fault can kill the daemon thread and turn
        # capture into a silent black hole; the error is surfaced via on_send_error and we loop on.
        try:
            try:
                item = _event_q.get(timeout=idle_flush)
            except queue_lib.Empty:
                _flush_pending_batches(pending, client, options, batch_size)
                continue

            if item is _SENTINEL:
                _flush_pending_batches(pending, client, options, batch_size)
                break

            pending.append(item)

            while len(pending) >= batch_size:
                _flush_pending_batches(pending, client, options, batch_size)
        except Exception as ex:  # noqa: BLE001 — worker must survive anything
            _safe_report_error(options.on_send_error, ex)


def initialize(options: ChurnWarnOptions) -> None:
    global _thread, _event_q, _http, _opts, _preferred_batch_size, _idle_flush_seconds

    if not (options.base_url or "").strip():
        raise ValueError("base_url is required")

    api_key = (options.api_key or "").strip()
    tok = _normalize_bearer(options.api_token or "") if options.api_token else ""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    elif tok:
        headers["Authorization"] = f"Bearer {tok}"
    else:
        raise ValueError("Either api_key or api_token is required")

    # Serialize against a concurrent initialize()/shutdown() so globals aren't swapped mid-setup.
    with _lifecycle_lock:
        shutdown(wait=True, timeout_sec=15.0)

        base = options.base_url.rstrip("/") + "/"
        _preferred_batch_size = max(
            1, min(options.batch_size if options.batch_size > 0 else 50, MAX_EVENTS_PER_BATCH)
        )
        _idle_flush_seconds = (
            options.flush_interval_seconds if options.flush_interval_seconds > 0 else 5.0
        )

        maxq = options.max_queue_size if options.max_queue_size > 0 else 10_000
        _event_q = queue_lib.Queue(maxsize=maxq)
        _http = httpx.Client(base_url=base, headers=headers, timeout=httpx.Timeout(60.0))
        _opts = options
        _stop.clear()

        t = threading.Thread(target=_background_sender_loop, name="churn-warn-sdk", daemon=True)
        _thread = t
        t.start()


def shutdown(*, wait: bool = True, timeout_sec: float = 15.0) -> None:
    global _thread, _event_q, _http, _opts

    with _lifecycle_lock:
        _stop.set()
        q_inst = _event_q
        th = _thread
        cli = _http

        if q_inst is not None:
            try:
                q_inst.put(_SENTINEL, timeout=timeout_sec)
            except queue_lib.Full:
                pass

        if wait and th is not None and th.is_alive():
            th.join(timeout=timeout_sec)

        if cli is not None:
            try:
                cli.close()
            except Exception:
                pass

        _thread = None
        _event_q = None
        _http = None
        _opts = None


def capture_event(
    external_account_id: str | RecordEventInput,
    event_type: Optional[str] = None,
    *,
    payload: Optional[Mapping[str, Any]] = None,
    payload_json: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    idempotency_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    # Snapshot the globals so a concurrent shutdown() swapping them to None can't cause an
    # AttributeError partway through this call (lock-free on the capture hot path).
    q = _event_q
    opts = _opts
    if q is None or opts is None:
        raise RuntimeError("Call initialize(ChurnWarnOptions(...)) before capture_event.")

    if isinstance(external_account_id, RecordEventInput):
        inp = external_account_id
    else:
        inp = RecordEventInput(
            external_account_id=str(external_account_id).strip(),
            event_type=str(event_type or "").strip(),
            source=source,
            occurred_at=occurred_at,
            payload_json=payload_json,
            payload=dict(payload) if payload is not None else None,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
        )

    if not inp.external_account_id.strip():
        raise ValueError("external_account_id is required")
    if not inp.event_type.strip():
        raise ValueError("event_type is required")

    # User hook runs on the caller's thread (intentional — user controls timing)
    if opts.on_before_enqueue is not None:
        try:
            inp = opts.on_before_enqueue(inp)
        except Exception:
            pass
    # Built-in redaction runs in _post_events_batch (background flush thread)

    try:
        q.put_nowait(inp)
    except queue_lib.Full:
        _safe_report_error(
            opts.on_send_error, RuntimeError(f"capture queue full (max {opts.max_queue_size})")
        )


def upsert_account(
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
    """Upsert slow-changing account facts via ``PUT /api/accounts/{externalId}``.

    Only fields you pass are written. Unlike :func:`capture_event`, this is a synchronous
    call on the caller's thread and raises :class:`ChurnWarnApiError` on a non-2xx response.
    Use it for account attributes/flags (``direct_deposit``, ``push_opt_in``, ``role`` …)
    and the commercial block — not for time-series metrics, which belong in events.
    """
    if _http is None:
        raise RuntimeError("Call initialize(ChurnWarnOptions(...)) before upsert_account.")
    ext = _truncate(str(external_account_id or "").strip(), 100)
    if not ext:
        raise ValueError("external_account_id is required")

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
    r = _http.put(f"api/accounts/{quote(ext, safe='')}", json=body)
    if not (200 <= r.status_code < 300):
        raise ChurnWarnApiError(r.status_code, r.reason_phrase or "", r.text)


__all__ = [
    "ChurnWarnApiError",
    "ChurnWarnOptions",
    "MAX_EVENTS_PER_BATCH",
    "capture_event",
    "initialize",
    "shutdown",
    "upsert_account",
]
