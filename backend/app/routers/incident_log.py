import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Incident
from app.schemas.incident_record import IncidentRecordRead

router = APIRouter(prefix="/incident-log", tags=["incident-log"])


@router.get("/", response_model=list[IncidentRecordRead])
async def list_incidents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Incident).order_by(Incident.created_at.desc()))
    return result.scalars().all()


@router.get("/{id}", response_model=IncidentRecordRead)
async def get_incident(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    incident = await db.get(Incident, id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident
