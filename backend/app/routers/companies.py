import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Company
from app.schemas.kb import CompanyCreate, CompanyUpdate, CompanyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=list[CompanyRead])
async def list_companies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company))
    return result.scalars().all()


@router.post("/", response_model=CompanyRead, status_code=201)
async def create_company(body: CompanyCreate, db: AsyncSession = Depends(get_db)):
    company = Company(**body.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


@router.get("/{id}", response_model=CompanyRead)
async def get_company(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    company = await db.get(Company, id)
    if not company:
        raise HTTPException(404, "Company not found")
    return company


@router.put("/{id}", response_model=CompanyRead)
async def update_company(id: uuid.UUID, body: CompanyUpdate, db: AsyncSession = Depends(get_db)):
    company = await db.get(Company, id)
    if not company:
        raise HTTPException(404, "Company not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(company, k, v)
    await db.commit()
    await db.refresh(company)
    return company
