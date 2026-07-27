"""Privacy helpers: bounded sensitive-data masking and safe URL extraction."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

_MASK_BUDGET_SEC = 0.05

MASK_DEFAULT = "***"
MASK_PASSWORD = "********"
MASK_CARD = "****"
MAX_SCAN = 2048

CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.I)
CREDIT_CARD_RE = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{16}\b")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b")
SSN_RE = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\b")
API_KEY_RE = re.compile(
    r"\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|bearer)\s*[:=]\s*[\"']?([A-Za-z0-9_-]{20,})[\"']?",
    re.I,
)
URL_PASSWORD_RE = re.compile(r"([a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)", re.I)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}[A-Z0-9]{0,16}\b", re.I)
SENSITIVE_KEY_RE = re.compile(
    r"password|secret|token|api[_-]?key|apikey|authorization|cookie|ssn|credit[_-]?card",
    re.I,
)


def sanitize_for_telemetry(value: object, max_len: int = MAX_SCAN) -> str:
    text = "" if value is None else str(value)
    text = CONTROL_CHARS_RE.sub("", text)
    return text[:max_len]


def _mask_email(email: str) -> str:
    at = email.find("@")
    if at <= 0 or at >= len(email) - 1:
        return MASK_DEFAULT
    user = email[:at]
    domain = email[at + 1 :]
    if len(user) <= 2:
        return f"{MASK_DEFAULT}@{domain}"
    return f"{user[0]}{MASK_DEFAULT}{user[-1]}@{domain}"


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _mask_phone(m: re.Match) -> str:  # type: ignore[type-arg]
    digits = _digits_only(m.group(0))
    if len(digits) < 7:
        return MASK_DEFAULT
    return digits[:3] + "****" + digits[-4:]


def mask_sensitive_text(value: object, max_len: int = MAX_SCAN) -> str:
    result = sanitize_for_telemetry(value, max_len)
    if not result:
        return result

    deadline = time.monotonic() + _MASK_BUDGET_SEC

    def step(pattern: re.Pattern, repl: object) -> None:  # type: ignore[type-arg]
        nonlocal result
        if time.monotonic() >= deadline:
            return
        try:
            result = pattern.sub(repl, result)  # type: ignore[arg-type]
        except Exception:
            pass

    step(JWT_RE, lambda m: m.group(0)[:10] + "..." + MASK_DEFAULT if len(m.group(0)) > 20 else MASK_DEFAULT)
    step(API_KEY_RE, lambda m: m.group(0).replace(m.group(1), m.group(1)[:4] + MASK_DEFAULT))
    step(URL_PASSWORD_RE, r"\1" + MASK_PASSWORD + r"\3")
    step(CREDIT_CARD_RE, lambda m: "****-****-****-" + _digits_only(m.group(0))[-4:])
    step(IBAN_RE, lambda m: m.group(0)[:4] + MASK_DEFAULT + m.group(0)[-4:])
    step(SSN_RE, "***-**-****")
    step(PHONE_RE, _mask_phone)
    step(EMAIL_RE, lambda m: _mask_email(m.group(0)))
    return result


def safe_url_string(value: object) -> str:
    raw = sanitize_for_telemetry(value)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.scheme:
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return parts.path
    except Exception:
        return mask_sensitive_text(raw.split("#", 1)[0].split("?", 1)[0], 512)


def _is_url_key(key: str) -> bool:
    lower = key.lower()
    return lower == "url" or lower == "referrer" or lower.endswith("url")


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_RE.search(key))


def _redact_value(value: Any, depth: int) -> Any:
    if value is None or depth > 8:
        return value
    if isinstance(value, str):
        return mask_sensitive_text(value, MAX_SCAN)
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return [_redact_value(v, depth + 1) for v in value[:100]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in list(value.keys())[:100]:
            v = value[key]
            if _is_sensitive_key(key):
                out[key] = MASK_DEFAULT
            elif _is_url_key(key):
                out[key] = safe_url_string(v)
            else:
                out[key] = _redact_value(v, depth + 1)
        return out
    return value


def redact_payload(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if payload is None:
        return {}
    try:
        result = _redact_value(dict(payload), 0)
        return result if isinstance(result, dict) else dict(payload)
    except Exception:
        return dict(payload)


def redact_payload_json(json_str: Optional[str]) -> str:
    if json_str is None or json_str == "":
        return "{}"
    try:
        parsed = json.loads(json_str)
        return json.dumps(_redact_value(parsed, 0), separators=(",", ":"))
    except Exception:
        return mask_sensitive_text(json_str, MAX_SCAN)
