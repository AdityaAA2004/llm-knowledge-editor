import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Triple
from app.schemas.triple import TripleRead

router = APIRouter(prefix="/triples", tags=["triples"])


@router.get("/", response_model=list[TripleRead])
async def list_triples(
    scope: str | None = Query(None),
    committed: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Triple)
    if scope is not None:
        q = q.where(Triple.scope == scope)
    if committed is not None:
        q = q.where(Triple.committed == committed)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{id}", response_model=TripleRead)
async def get_triple(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    triple = await db.get(Triple, id)
    if not triple:
        raise HTTPException(404, "Triple not found")
    return triple
