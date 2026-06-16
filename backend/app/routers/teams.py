import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import FeatureTeam, API
from app.schemas.kb import FeatureTeamCreate, FeatureTeamUpdate, FeatureTeamRead
from app.services.kb_service import (
    derive_and_save_team_triples,
    replace_triples_for_source,
    mark_triples_pending_erasure,
)

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("/", response_model=list[FeatureTeamRead])
async def list_teams(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FeatureTeam).where(FeatureTeam.deleted_at.is_(None)))
    return result.scalars().all()


@router.post("/", response_model=FeatureTeamRead, status_code=201)
async def create_team(body: FeatureTeamCreate, db: AsyncSession = Depends(get_db)):
    team = FeatureTeam(**body.model_dump())
    db.add(team)
    await db.flush()
    await derive_and_save_team_triples(db, team)
    await db.commit()
    await db.refresh(team)
    return team


@router.get("/{id}", response_model=FeatureTeamRead)
async def get_team(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    team = await db.get(FeatureTeam, id)
    if not team or team.deleted_at:
        raise HTTPException(404, "Team not found")
    return team


@router.put("/{id}", response_model=FeatureTeamRead)
async def update_team(id: uuid.UUID, body: FeatureTeamUpdate, db: AsyncSession = Depends(get_db)):
    team = await db.get(FeatureTeam, id)
    if not team or team.deleted_at:
        raise HTTPException(404, "Team not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(team, k, v)
    await replace_triples_for_source(db, team.id, "team")
    await derive_and_save_team_triples(db, team)
    await db.commit()
    await db.refresh(team)
    return team


@router.delete("/{id}", status_code=204)
async def delete_team(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    team = await db.get(FeatureTeam, id)
    if not team or team.deleted_at:
        raise HTTPException(404, "Team not found")
    active_api = await db.execute(
        select(API).where(API.team_id == id, API.deleted_at.is_(None)).limit(1)
    )
    if active_api.scalar_one_or_none():
        raise HTTPException(409, "Team still owns active APIs. Reassign or delete them first.")
    team.deleted_at = datetime.now(timezone.utc)
    await mark_triples_pending_erasure(db, team.id, "team")
    await db.commit()
