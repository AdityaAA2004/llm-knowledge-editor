import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import API
from app.schemas.kb import APICreate, APIUpdate, APIRead
from app.services.kb_service import (
    derive_and_save_api_triples,
    replace_triples_for_source,
    mark_triples_pending_erasure,
)

router = APIRouter(prefix="/apis", tags=["apis"])


@router.get("/", response_model=list[APIRead])
async def list_apis(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(API).where(API.deleted_at.is_(None)))
    return result.scalars().all()


@router.post("/", response_model=APIRead, status_code=201)
async def create_api(body: APICreate, db: AsyncSession = Depends(get_db)):
    api = API(**body.model_dump())
    db.add(api)
    await db.flush()
    await derive_and_save_api_triples(db, api)
    await db.commit()
    await db.refresh(api)
    return api


@router.get("/{id}", response_model=APIRead)
async def get_api(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    api = await db.get(API, id)
    if not api or api.deleted_at:
        raise HTTPException(404, "API not found")
    return api


@router.put("/{id}", response_model=APIRead)
async def update_api(id: uuid.UUID, body: APIUpdate, db: AsyncSession = Depends(get_db)):
    api = await db.get(API, id)
    if not api or api.deleted_at:
        raise HTTPException(404, "API not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(api, k, v)
    await replace_triples_for_source(db, api.id, "api")
    await derive_and_save_api_triples(db, api)
    await db.commit()
    await db.refresh(api)
    return api


@router.delete("/{id}", status_code=204)
async def delete_api(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    api = await db.get(API, id)
    if not api or api.deleted_at:
        raise HTTPException(404, "API not found")
    api.deleted_at = datetime.now(timezone.utc)
    await mark_triples_pending_erasure(db, api.id, "api")
    await db.commit()
