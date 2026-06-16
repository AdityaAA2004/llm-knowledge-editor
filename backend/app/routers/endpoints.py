import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Endpoint, EndpointVariant
from app.schemas.kb import (
    EndpointCreate, EndpointUpdate, EndpointRead,
    EndpointVariantCreate, EndpointVariantUpdate, EndpointVariantRead,
)
from app.services.kb_service import (
    derive_and_save_endpoint_triples,
    derive_and_save_variant_triples,
    replace_triples_for_source,
    mark_triples_pending_erasure,
)

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[EndpointRead])
async def list_endpoints(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Endpoint).where(Endpoint.deleted_at.is_(None)))
    return result.scalars().all()


@router.post("/", response_model=EndpointRead, status_code=201)
async def create_endpoint(body: EndpointCreate, db: AsyncSession = Depends(get_db)):
    endpoint = Endpoint(**body.model_dump())
    db.add(endpoint)
    await db.flush()
    await derive_and_save_endpoint_triples(db, endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.get("/{id}", response_model=EndpointRead)
async def get_endpoint(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    endpoint = await db.get(Endpoint, id)
    if not endpoint or endpoint.deleted_at:
        raise HTTPException(404, "Endpoint not found")
    return endpoint


@router.put("/{id}", response_model=EndpointRead)
async def update_endpoint(id: uuid.UUID, body: EndpointUpdate, db: AsyncSession = Depends(get_db)):
    endpoint = await db.get(Endpoint, id)
    if not endpoint or endpoint.deleted_at:
        raise HTTPException(404, "Endpoint not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(endpoint, k, v)
    await replace_triples_for_source(db, endpoint.id, "endpoint")
    await derive_and_save_endpoint_triples(db, endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.delete("/{id}", status_code=204)
async def delete_endpoint(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    endpoint = await db.get(Endpoint, id)
    if not endpoint or endpoint.deleted_at:
        raise HTTPException(404, "Endpoint not found")
    endpoint.deleted_at = datetime.now(timezone.utc)
    await mark_triples_pending_erasure(db, endpoint.id, "endpoint")
    await db.commit()


# ── Variants (nested) ──────────────────────────────────────────────────────────

@router.get("/{endpoint_id}/variants/", response_model=list[EndpointVariantRead])
async def list_variants(endpoint_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(EndpointVariant).where(
            EndpointVariant.endpoint_id == endpoint_id,
            EndpointVariant.deleted_at.is_(None),
        )
    )
    return result.scalars().all()


@router.post("/{endpoint_id}/variants/", response_model=EndpointVariantRead, status_code=201)
async def create_variant(endpoint_id: uuid.UUID, body: EndpointVariantCreate, db: AsyncSession = Depends(get_db)):
    endpoint = await db.get(Endpoint, endpoint_id)
    if not endpoint or endpoint.deleted_at:
        raise HTTPException(404, "Endpoint not found")
    variant = EndpointVariant(endpoint_id=endpoint_id, **body.model_dump())
    db.add(variant)
    await db.flush()
    await derive_and_save_variant_triples(db, variant)
    await db.commit()
    await db.refresh(variant)
    return variant


@router.get("/{endpoint_id}/variants/{vid}", response_model=EndpointVariantRead)
async def get_variant(endpoint_id: uuid.UUID, vid: uuid.UUID, db: AsyncSession = Depends(get_db)):
    variant = await db.get(EndpointVariant, vid)
    if not variant or variant.endpoint_id != endpoint_id or variant.deleted_at:
        raise HTTPException(404, "Variant not found")
    return variant


@router.put("/{endpoint_id}/variants/{vid}", response_model=EndpointVariantRead)
async def update_variant(endpoint_id: uuid.UUID, vid: uuid.UUID, body: EndpointVariantUpdate, db: AsyncSession = Depends(get_db)):
    variant = await db.get(EndpointVariant, vid)
    if not variant or variant.endpoint_id != endpoint_id or variant.deleted_at:
        raise HTTPException(404, "Variant not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(variant, k, v)
    await replace_triples_for_source(db, variant.id, "variant")
    await derive_and_save_variant_triples(db, variant)
    await db.commit()
    await db.refresh(variant)
    return variant


@router.delete("/{endpoint_id}/variants/{vid}", status_code=204)
async def delete_variant(endpoint_id: uuid.UUID, vid: uuid.UUID, db: AsyncSession = Depends(get_db)):
    variant = await db.get(EndpointVariant, vid)
    if not variant or variant.endpoint_id != endpoint_id or variant.deleted_at:
        raise HTTPException(404, "Variant not found")
    variant.deleted_at = datetime.now(timezone.utc)
    await mark_triples_pending_erasure(db, variant.id, "variant")
    await db.commit()
