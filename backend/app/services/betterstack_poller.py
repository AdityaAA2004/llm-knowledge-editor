"""Polls Better Stack's ClickHouse-compatible Logs Query API for recent
error-level entries and feeds them into the same incident pipeline the
(unused-for-now) webhook receiver was built for.

Chosen over Better Stack's native alert -> outgoing-webhook wiring because
that path routes through their Uptime/Incident-Management escalation system
in a way that wasn't reliably reproducible from their docs. Polling is fully
within our control: no cursor/state to persist, since `build_incident_from_log`
already dedupes by `external_id` — each tick just re-queries a sliding lookback
window and lets already-processed entries fall out naturally.
"""

import asyncio
import json
import logging
import os

import httpx

from app.db import AsyncSessionLocal
from app.services.incident_service import build_incident_from_log

logger = logging.getLogger(__name__)

_QUERY_TEMPLATE = (
    "SELECT dt, raw FROM remote({table}) "
    "WHERE dt > now() - INTERVAL {lookback_s} SECOND "
    "AND JSONExtractString(raw, 'level') = 'error' "
    "ORDER BY dt ASC LIMIT 200 FORMAT JSONEachRow"
)


def _poller_configured() -> bool:
    return all(
        os.environ.get(k)
        for k in ("BETTERSTACK_QUERY_HOST", "BETTERSTACK_QUERY_USERNAME", "BETTERSTACK_QUERY_PASSWORD", "BETTERSTACK_LOGS_TABLE")
    )


async def _fetch_recent_error_logs(lookback_s: int) -> list[dict]:
    host = os.environ["BETTERSTACK_QUERY_HOST"]
    username = os.environ["BETTERSTACK_QUERY_USERNAME"]
    password = os.environ["BETTERSTACK_QUERY_PASSWORD"]
    table = os.environ["BETTERSTACK_LOGS_TABLE"]

    query = _QUERY_TEMPLATE.format(table=table, lookback_s=lookback_s)
    url = f"https://{host}?output_format_pretty_row_numbers=0"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, content=query, auth=(username, password))
        response.raise_for_status()

    logs = []
    for line in response.text.strip().splitlines():
        if not line:
            continue
        row = json.loads(line)
        try:
            log = json.loads(row["raw"])
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Skipping unparseable Better Stack row: %r", row)
            continue
        log.setdefault("dt", row.get("dt"))
        logs.append(log)
    return logs


async def poll_loop(interval_s: int, lookback_s: int) -> None:
    if not _poller_configured():
        logger.info("Better Stack polling not configured (missing BETTERSTACK_QUERY_* env vars) — skipping.")
        return

    logger.info("Starting Better Stack error-log poller (every %ss, %ss lookback)", interval_s, lookback_s)
    while True:
        try:
            logs = await _fetch_recent_error_logs(lookback_s)
            async with AsyncSessionLocal() as db:
                for log in logs:
                    try:
                        await build_incident_from_log(db, log)
                    except Exception:
                        logger.exception("Failed to process polled log entry: %r", log)
        except Exception:
            logger.exception("Better Stack poll tick failed")

        await asyncio.sleep(interval_s)
