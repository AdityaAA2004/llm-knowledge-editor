import logging
import os
import random
import traceback
from contextlib import asynccontextmanager
from typing import Callable

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from db import get_db_session
from logging_client import send_log
from routes_loader import RouteSpec, load_route_specs

logger = logging.getLogger("mockprod")

ERROR_RATE = float(os.environ.get("MOCKPROD_ERROR_RATE", "0.15"))
_ERROR_STATUS_CODES = [400, 404, 500, 502, 503]


def _simulate_error(spec: RouteSpec) -> tuple[int, dict, str]:
    """Deliberately trigger and capture a real Python exception/stack trace."""
    try:
        broken_payload: dict = {}
        _ = broken_payload["missing_key"]  # raises KeyError on purpose
    except Exception:
        stack_trace = traceback.format_exc()

    status_code = random.choice(_ERROR_STATUS_CODES)
    message = f"Simulated failure handling {spec.http_method} {spec.db_path}"
    return status_code, {"error": message, "status_code": status_code}, stack_trace


def _make_handler(spec: RouteSpec) -> Callable:
    async def handler(request: Request):
        request_body = None
        if spec.http_method in {"POST", "PUT", "PATCH"}:
            try:
                request_body = await request.json()
            except Exception:
                request_body = None

        if random.random() < ERROR_RATE:
            status_code, response_body, stack_trace = _simulate_error(spec)
            await send_log(
                {
                    "level": "error",
                    "method": spec.http_method,
                    "path": spec.db_path,
                    "service": spec.service_name,
                    "api_name": spec.api_name,
                    "endpoint_id": spec.endpoint_id,
                    "request_body": request_body,
                    "response_body": response_body,
                    "status_code": status_code,
                    "message": response_body["error"],
                    "stack_trace": stack_trace,
                }
            )
            return JSONResponse(status_code=status_code, content=response_body)

        variant = random.choice(spec.variants) if spec.variants else None
        response_body = (variant or {}).get("response_200_json") or {"status": "ok"}
        await send_log(
            {
                "level": "info",
                "method": spec.http_method,
                "path": spec.db_path,
                "service": spec.service_name,
                "api_name": spec.api_name,
                "endpoint_id": spec.endpoint_id,
                "request_body": request_body,
                "response_body": response_body,
                "status_code": 200,
                "message": "ok",
                "stack_trace": None,
            }
        )
        return JSONResponse(status_code=200, content=response_body)

    return handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db_session() as session:
        specs = load_route_specs(session)
    for spec in specs:
        app.add_api_route(spec.fastapi_path, _make_handler(spec), methods=[spec.http_method])
    logger.info("Registered %d mock production routes", len(specs))
    yield


app = FastAPI(title="Mock Production API", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
