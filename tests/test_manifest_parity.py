"""Parity between the SDK constants and sdks/signals.manifest.json, plus the account body builder."""

import json
from pathlib import Path

import pytest

from churn_warn_sdk import (
    AccountAttributes,
    BusinessTypes,
    PayloadFields,
    constants_metrics,
    constants_raw,
)
from churn_warn_sdk.accounts import build_account_body


def _load_manifest():
    # The shared manifest lives at sdks/signals.manifest.json in the monorepo. A standalone SDK
    # repo doesn't ship it (parity is verified at source in the monorepo), so the parity tests
    # skip rather than fail when it's absent. A repo-root copy is also honored if vendored.
    here = Path(__file__).resolve()
    for p in (here.parent.parent.parent / "signals.manifest.json", here.parent.parent / "signals.manifest.json"):
        try:
            return json.loads(p.read_text())
        except OSError:
            continue
    return None


_MANIFEST = _load_manifest()
_needs_manifest = pytest.mark.skipif(
    _MANIFEST is None, reason="signals.manifest.json not found (standalone repo)"
)


def _manifest_values(group: dict) -> set[str]:
    out: set[str] = set()
    for key, val in group.items():
        if key.startswith("$"):
            continue
        if isinstance(val, list):
            out.update(v for v in val if isinstance(v, str))
        elif isinstance(val, str):
            out.add(val)
    return out


def _module_str_values(module) -> set[str]:
    return {
        v
        for name, v in vars(module).items()
        if not name.startswith("_") and isinstance(v, str)
    }


def _class_str_values(cls) -> set[str]:
    return {
        v
        for name, v in vars(cls).items()
        if not name.startswith("_") and isinstance(v, str)
    }


@_needs_manifest
def test_metrics_match_manifest():
    assert _module_str_values(constants_metrics) == _manifest_values(_MANIFEST["metricKeys"])


@_needs_manifest
def test_raw_events_are_known_aliases():
    aliases = _MANIFEST["rawAliases"]
    for raw in _module_str_values(constants_raw):
        assert raw in aliases, f"alias {raw} missing from manifest"


@_needs_manifest
def test_extra_constants_match_manifest():
    assert _class_str_values(PayloadFields) == _manifest_values(_MANIFEST["payloadFields"])
    assert _class_str_values(AccountAttributes) == _manifest_values(_MANIFEST["accountAttributes"])
    assert _class_str_values(BusinessTypes) == _manifest_values(_MANIFEST["businessTypes"])


def test_build_account_body_only_includes_passed_fields_and_lowercases_enums():
    body = build_account_body(
        plan_key="pro",
        value_basis="LTV",
        role="Buyer",
        attributes={"push_opt_in": True},
    )
    assert body == {
        "planKey": "pro",
        "valueBasis": "ltv",
        "role": "buyer",
        "attributes": {"push_opt_in": True},
    }


def test_build_account_body_empty_when_nothing_passed():
    assert build_account_body() == {}
