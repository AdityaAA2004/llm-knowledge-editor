import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.betterstack import parse_betterstack_payload
from app.services.incident_service import build_incident_from_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["incident-webhook"])


@router.post("/betterstack/{token}")
async def receive_betterstack_alert(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    expected_token = os.environ.get("BETTERSTACK_WEBHOOK_TOKEN")
    if not expected_token or token != expected_token:
        raise HTTPException(403, "Invalid webhook token")

    payload = await request.json()
    logs = parse_betterstack_payload(payload)

    processed = 0
    for log in logs:
        try:
            await build_incident_from_log(db, log)
            processed += 1
        except Exception:
            # A single malformed/unmatched log entry must never fail the whole
            # webhook delivery — Better Stack would otherwise retry-storm on a 500.
            logger.exception("Failed to process incoming log entry: %r", log)

    return {"status": "ok", "processed": processed}
