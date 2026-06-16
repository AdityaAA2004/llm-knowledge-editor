import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, FeatureTeam, API, Endpoint, EndpointVariant, Triple


def _t(subject: str, relation: str, object_: str, scope: str, source_id: uuid.UUID, source_type: str) -> Triple:
    return Triple(
        subject=subject,
        relation=relation,
        object=object_,
        scope=scope,
        source_id=source_id,
        source_type=source_type,
    )


async def derive_and_save_team_triples(db: AsyncSession, team: FeatureTeam) -> None:
    company = await db.get(Company, team.company_id)
    triples = [_t(team.name, "belongs_to_company", company.name, "team", team.id, "team")]
    if team.tech_lead:
        triples.append(_t(team.name, "tech_lead", team.tech_lead, "team", team.id, "team"))
    db.add_all(triples)


async def derive_and_save_api_triples(db: AsyncSession, api: API) -> None:
    team = await db.get(FeatureTeam, api.team_id)
    triples = [_t(api.name, "owned_by_team", team.name, "api", api.id, "api")]
    if api.description:
        triples.append(_t(api.name, "description", api.description, "api", api.id, "api"))
    if api.point_of_contact:
        triples.append(_t(api.name, "point_of_contact", api.point_of_contact, "api", api.id, "api"))
    db.add_all(triples)


async def derive_and_save_endpoint_triples(db: AsyncSession, endpoint: Endpoint) -> None:
    api = await db.get(API, endpoint.api_id)
    subject = f"{endpoint.http_method} {endpoint.path}"
    triples = [_t(subject, "belongs_to_api", api.name, "endpoint", endpoint.id, "endpoint")]
    if endpoint.business_function:
        triples.append(_t(subject, "business_function", endpoint.business_function, "endpoint", endpoint.id, "endpoint"))
    db.add_all(triples)


async def derive_and_save_variant_triples(db: AsyncSession, variant: EndpointVariant) -> None:
    endpoint = await db.get(Endpoint, variant.endpoint_id)
    subject = f"{endpoint.http_method} {endpoint.path} [{variant.client_type}]"
    triples = []
    if variant.request_body_json:
        triples.append(_t(subject, "request_body", json.dumps(variant.request_body_json), "variant", variant.id, "variant"))
    if variant.response_200_json:
        triples.append(_t(subject, "response_200", json.dumps(variant.response_200_json), "variant", variant.id, "variant"))
    if triples:
        db.add_all(triples)


async def replace_triples_for_source(db: AsyncSession, source_id: uuid.UUID, source_type: str) -> None:
    result = await db.execute(
        select(Triple).where(Triple.source_id == source_id, Triple.source_type == source_type)
    )
    for t in result.scalars().all():
        if t.committed:
            t.pending_erasure = True
        else:
            await db.delete(t)


async def mark_triples_pending_erasure(db: AsyncSession, source_id: uuid.UUID, source_type: str) -> None:
    result = await db.execute(
        select(Triple).where(Triple.source_id == source_id, Triple.source_type == source_type)
    )
    for t in result.scalars().all():
        t.pending_erasure = True
