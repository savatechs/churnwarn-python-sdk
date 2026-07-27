# ChurnWarn Python SDK

Background **capture** API (`initialize` / `capture_event` / `shutdown`), plus an optional **async** `ChurnWarnClient` for direct `POST /api/events` and `/api/events/batch`.

Requires **Python 3.9+** and **httpx**.

## Install (editable, from repo)

```bash
cd sdks/churn_warn_python_sdk
pip install -e .
```

For a quick local run without install, set `PYTHONPATH=src`.

## Capture API (recommended)

Call **`initialize`** once, then **`capture_event`** from anywhere; events are queued and sent in a background thread to **`POST /api/events/batch`**. Use **`shutdown`** to drain and stop.

```python
from churn_warn_sdk import (
    ChurnWarnOptions,
    Metrics,
    RawEvents,
    RecordEventInput,
    capture_event,
    initialize,
    shutdown,
)

initialize(
    ChurnWarnOptions(
        base_url="https://your-gateway.example.com",
        api_token="your-jwt",  # or api_key="..." for X-Api-Key
        default_tenant_id=None,
        default_source="python_sdk",
        batch_size=50,
        flush_interval_seconds=5.0,
        max_queue_size=10_000,
        on_send_error=lambda e: print("send failed", e),
    )
)

capture_event("acct-1", Metrics.LOGIN, payload={"path": "/"})

capture_event(
    RecordEventInput(
        external_account_id="acct-2",
        event_type=RawEvents.APP_LOGIN,
        payload={"x": 1},
    )
)

shutdown()
```

### Auth

- **`api_key`** → `X-Api-Key` header.
- **`api_token`** → `Authorization: Bearer …` (a `Bearer ` prefix on the string is stripped).

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `base_url` | required | Gateway root URL |
| `api_key` | — | `X-Api-Key` header (preferred for servers) |
| `api_token` | — | Bearer JWT when `api_key` is not set |
| `default_tenant_id` | `None` | Applied when events omit `tenant_id` |
| `default_source` | `python_sdk` | Event `source` field |
| `batch_size` | `50` | Max events per flush (capped at **500** per HTTP request) |
| `flush_interval_seconds` | `5.0` | Max wait before sending a non-empty queue |
| `max_queue_size` | `10000` | When full, the event is dropped and `on_send_error` is invoked |
| `max_retries` | `3` | Retry attempts after the first try for a failed flush (`0` disables) |
| `retry_base_delay_seconds` | `0.5` | Base delay for exponential backoff between retries |
| `retry_max_delay_seconds` | `30.0` | Upper bound on any single backoff delay |
| `redact_payload` | `True` | Mask common sensitive patterns before enqueue |
| `on_before_enqueue` | — | Optional hook to transform events before they enter the queue |
| `on_send_error` | — | Network or non-success HTTP errors during batch send (a full capture queue reports a `RuntimeError`) |

The HTTP request timeout is fixed at **60s** per batch request.

## Retries and delivery

A failed batch flush is retried up to **`max_retries`** times with exponential backoff and equal
jitter (delay = `min(retry_max_delay_seconds, retry_base_delay_seconds × 2ⁿ)`, half fixed / half
random), capped by **`retry_max_delay_seconds`**.

Only **transient** failures are retried:

- network errors and request timeouts (`httpx.RequestError`)
- HTTP **429** and **5xx**

Everything else (**4xx** other than 429 — bad auth, validation errors) fails immediately and is
reported through **`on_send_error`**; retrying would not help. Every event carries an
`idempotency_key`, so a retried batch **never duplicates events** server-side.

Retries run on the background sender thread with blocking sleeps, so they never block the
`capture_event` caller. When all attempts are exhausted, the batch is dropped and the final
exception goes to **`on_send_error`**.

## Account facts — `upsert_account(external_id, ...)`

Some dashboard-template signals are **slow-changing account facts**, not events: the fintech
`direct_deposit`/`kyc_completed` flags, a marketplace account's `role`, or a headline money
figure. Write them with **`upsert_account`**, which `PUT`s to `/api/accounts/{external_id}`.
Unlike `capture_event`, it runs synchronously on the caller's thread and raises
`ChurnWarnApiError` on a non-2xx response. Only fields you pass are written.

```python
from churn_warn_sdk import upsert_account, AccountAttributes, BusinessTypes

upsert_account(
    "acct-1",
    business_type=BusinessTypes.FINTECH,
    monetary_value=2450.0,
    value_basis="balance",
    role="buyer",  # marketplace side
    attributes={AccountAttributes.DIRECT_DEPOSIT: True, "kyc_completed": True},
)
```

Known keyword args (`name`, `email`, `kind`, `business_type`, `monetary_value`, `value_basis`,
`currency`, `plan_key`, `lifecycle_stage`, `renewal_at`, `status`, `role`) map to account
columns; `attributes` merges into the fact bag (a `None` value removes a key). The async
`ChurnWarnClient` exposes the same method as `await client.upsert_account(...)`. Put
**metrics** in events, **facts** in `upsert_account`.

## Privacy and payload redaction

By default, payloads are redacted before enqueue:

- String values are scanned for emails, phone numbers, credit cards, SSN-like values, JWTs, API keys, and URL-embedded passwords.
- `url`, `referrer`, and keys ending in `url` have query strings and hashes stripped.
- Keys containing `password`, `secret`, `token`, `api_key`, `authorization`, `cookie`, `ssn`, or `credit_card` are replaced with `***`.

```python
from churn_warn_sdk import redact_payload, safe_url_string, mask_sensitive_text

initialize(
    ChurnWarnOptions(
        base_url="https://your-gateway.example.com",
        api_token="your-jwt",
        redact_payload=True,  # default
        on_before_enqueue=lambda inp: inp,  # optional
    )
)
```

- **`payload_json`** is parsed and redacted when possible; if parsing fails, the raw string is masked.
- Prefer **`path`** or **`route`** over full URLs in server-side payloads.
- Avoid using emails or usernames as `external_account_id` when a stable non-PII id is available.

## Async client (legacy / advanced)

Use **`async with ChurnWarnClient(...)`** when you want to await **`send_event`** / **`send_batch`** yourself (JWT only today). See constants and batch rules below.

```python
import asyncio
from churn_warn_sdk import ChurnWarnClient, Metrics, RecordEventInput


async def main():
    async with ChurnWarnClient(
        "https://your-gateway.example.com",
        "your-jwt",
        default_source="python_sdk",
        redact_payload=True,  # default
    ) as client:
        await client.send_event(
            RecordEventInput(
                external_account_id="acct-1",
                event_type=Metrics.LOGIN,
                payload={"path": "/"},
            )
        )


asyncio.run(main())
```

## Batch chunking

At most **500** events (`MAX_EVENTS_PER_BATCH`) per HTTP request; larger lists are split automatically in the async client.

## Tenant id in batches

If any event sets `tenant_id`, every non-null `tenant_id` in that batch must match. The value is sent once as batch-level `tenantId`, combined with `default_tenant_id` when all per-event values are omitted.

## Errors

- Capture path: failures are delivered to **`on_send_error`** when set; **`ChurnWarnApiError`** is used for non-success HTTP status in the sender.
- Async client: non-success HTTP raises **`ChurnWarnApiError`** (`status_code`, `body`).

## Constants

- **`Metrics`** — canonical metric strings (all business-type template signals).
- **`RawEvents`** — dotted raw vendor names the gateway maps to `Metrics`.
- **`PayloadFields`** — payload keys read by `sum_payload`/`avg_payload` (`value`, `side`, `quantity`).
- **`AccountAttributes`** — account fact keys (`direct_deposit`, `kyc_completed`, `push_opt_in`, `installed_at`).
- **`BusinessTypes`** — dashboard-template keys (`ecommerce`, `fintech`, `subscription_box`, `mobile`, `marketplace_buyer`, …).

All mirror `sdks/signals.manifest.json`; `tests/test_manifest_parity.py` asserts they stay in sync (`pip install -e '.[dev]' && pytest`).
