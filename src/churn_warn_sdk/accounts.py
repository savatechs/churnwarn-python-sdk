"""Shared request-body builder for the account-attributes write path (PUT /api/accounts/{externalId}).

Only fields the caller actually passes are included, matching the endpoint's
only-sent-fields-written semantics. Enum-like fields (kind / value_basis / status /
role) travel as lowercase strings; the gateway parses them case-insensitively.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

_UNSET = object()


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def build_account_body(
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
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if name is not _UNSET:
        body["name"] = name
    if email is not _UNSET:
        body["email"] = email
    if kind is not _UNSET:
        body["kind"] = str(kind).lower() if kind is not None else None
    if business_type is not _UNSET:
        body["businessType"] = business_type
    if monetary_value is not _UNSET:
        body["monetaryValue"] = monetary_value
    if value_basis is not _UNSET:
        body["valueBasis"] = str(value_basis).lower() if value_basis is not None else None
    if currency is not _UNSET:
        body["currency"] = currency
    if plan_key is not _UNSET:
        body["planKey"] = plan_key
    if lifecycle_stage is not _UNSET:
        body["lifecycleStage"] = lifecycle_stage
    if renewal_at is not _UNSET:
        body["renewalAt"] = _iso(renewal_at)
    if status is not _UNSET:
        body["status"] = str(status).lower() if status is not None else None
    if role is not _UNSET:
        body["role"] = str(role).lower() if role is not None else None
    if attributes is not None:
        body["attributes"] = dict(attributes)
    return body


ACCOUNT_BODY_UNSET = _UNSET
