"""Ships structured request/error log entries to Better Stack (Logtail).

Fire-and-forget: a logging failure must never break the mock production server
itself, so every error here is swallowed rather than raised.
"""

import os
from datetime import datetime, timezone
from typing import Any

import httpx


async def send_log(entry: dict[str, Any]) -> None:
    token = os.environ.get("BETTERSTACK_SOURCE_TOKEN")
    host = os.environ.get("BETTERSTACK_INGEST_HOST")
    if not token or not host:
        return

    payload = {"dt": datetime.now(timezone.utc).isoformat(), **entry}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"https://{host}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception:
        pass
