"""Defensive parsing of Better Stack's outgoing alert-webhook payload.

Better Stack's alert-webhook envelope shape isn't pinned down against live
docs here (Phase 0 only verified the *ingested* log JSON, which mockprod
controls itself) — this parser tries several plausible envelope shapes and
falls back to treating the whole payload as a single log record. Re-check
this against the actual payload Better Stack delivers on first real alert
(visible in Render request logs) and tighten it once confirmed.
"""

from typing import Any

_ENVELOPE_KEYS = ("payload", "logs", "data", "records", "events")


def _as_log_dict(raw: dict) -> dict:
    """Better Stack log fields may be nested under e.g. "dt"/"json"/"raw" —
    our own mockprod-authored fields (method, path, service, ...) are the
    ones that matter, so pull them out wherever they land."""
    candidate = raw.get("json") if isinstance(raw.get("json"), dict) else raw
    return {
        "method": candidate.get("method"),
        "path": candidate.get("path"),
        "service": candidate.get("service"),
        "api_name": candidate.get("api_name"),
        "endpoint_id": candidate.get("endpoint_id"),
        "request_body": candidate.get("request_body"),
        "response_body": candidate.get("response_body"),
        "status_code": candidate.get("status_code"),
        "message": candidate.get("message"),
        "stack_trace": candidate.get("stack_trace"),
        "external_id": raw.get("id") or candidate.get("dt"),
        "dt": candidate.get("dt"),
    }


def parse_betterstack_payload(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [_as_log_dict(item) for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in _ENVELOPE_KEYS:
            nested = payload.get(key)
            if isinstance(nested, list):
                return [_as_log_dict(item) for item in nested if isinstance(item, dict)]
            if isinstance(nested, dict):
                return [_as_log_dict(nested)]
        return [_as_log_dict(payload)]

    return []
