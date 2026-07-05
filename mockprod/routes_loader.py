"""Discovers the real KB endpoints from Postgres (read-only) so the mock production
server exposes the same routes the actual APIs would — this is what lets simulated
errors reference real services, endpoints, and request/response shapes.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_ENDPOINTS_SQL = text(
    """
    SELECT e.id, e.http_method, e.path, a.name AS api_name, t.name AS team_name
    FROM endpoint e
    JOIN api a ON a.id = e.api_id
    JOIN feature_team t ON t.id = a.team_id
    WHERE e.deleted_at IS NULL AND a.deleted_at IS NULL AND t.deleted_at IS NULL
    """
)

_VARIANTS_SQL = text(
    """
    SELECT request_body_json, response_200_json
    FROM endpoint_variant
    WHERE endpoint_id = :endpoint_id AND deleted_at IS NULL
    """
)


@dataclass
class RouteSpec:
    http_method: str
    db_path: str
    fastapi_path: str
    api_name: str
    service_name: str
    endpoint_id: str
    variants: list[dict[str, Any]] = field(default_factory=list)


def _to_fastapi_path(path: str) -> str:
    """KB paths use `:param` (e.g. /v1/payments/:paymentProcessId); FastAPI wants `{param}`."""
    return "/".join(
        f"{{{segment[1:]}}}" if segment.startswith(":") else segment for segment in path.split("/")
    )


def load_route_specs(session: Session) -> list[RouteSpec]:
    specs = []
    for row in session.execute(_ENDPOINTS_SQL).mappings():
        variants = [
            {"request_body_json": v["request_body_json"], "response_200_json": v["response_200_json"]}
            for v in session.execute(_VARIANTS_SQL, {"endpoint_id": row["id"]}).mappings()
        ]
        specs.append(
            RouteSpec(
                http_method=row["http_method"].upper(),
                db_path=row["path"],
                fastapi_path=_to_fastapi_path(row["path"]),
                api_name=row["api_name"],
                service_name=row["team_name"],
                endpoint_id=str(row["id"]),
                variants=variants,
            )
        )
    return specs
