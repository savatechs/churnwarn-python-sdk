"""ChurnWarn Python SDK: background capture (module API) and optional async HTTP client."""

from churn_warn_sdk import constants_metrics as Metrics
from churn_warn_sdk import constants_raw as RawEvents
from churn_warn_sdk.client import ChurnWarnClient
from churn_warn_sdk.constants_extra import (
    ACCOUNT_ROLES,
    VALUE_BASES,
    AccountAttributes,
    BusinessTypes,
    PayloadFields,
)
from churn_warn_sdk.models import (
    BatchItemResult,
    ChurnWarnApiError,
    EventRecordResult,
    RecordEventInput,
)
from churn_warn_sdk.privacy import mask_sensitive_text, redact_payload, redact_payload_json, safe_url_string
from churn_warn_sdk.sdk import (
    MAX_EVENTS_PER_BATCH,
    ChurnWarnOptions,
    capture_event,
    initialize,
    shutdown,
    upsert_account,
)

__all__ = [
    "ACCOUNT_ROLES",
    "VALUE_BASES",
    "AccountAttributes",
    "BatchItemResult",
    "BusinessTypes",
    "ChurnWarnApiError",
    "ChurnWarnClient",
    "ChurnWarnOptions",
    "EventRecordResult",
    "MAX_EVENTS_PER_BATCH",
    "Metrics",
    "PayloadFields",
    "RawEvents",
    "RecordEventInput",
    "capture_event",
    "initialize",
    "mask_sensitive_text",
    "redact_payload",
    "redact_payload_json",
    "safe_url_string",
    "shutdown",
    "upsert_account",
]
