"""Fires a mix of valid and deliberately malformed requests at a running mock
production server, so real error traffic (with real stack traces) lands in
Better Stack for the incident pipeline to pick up.

Run from inside mockprod/: `python simulate_errors.py --base-url https://<mockprod>.onrender.com`
"""

import argparse
import copy
import os
import random
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

from db import get_db_session
from routes_loader import RouteSpec, load_route_specs


def _concrete_path(spec: RouteSpec) -> str:
    """Replace {param} placeholders with a dummy value so real requests can be sent."""
    segments = [
        "demo-123" if segment.startswith("{") and segment.endswith("}") else segment
        for segment in spec.fastapi_path.split("/")
    ]
    return "/".join(segments)


def _malform(body: dict) -> dict:
    body = copy.deepcopy(body)
    if not body:
        return {"unexpected_field": 12345}
    key = random.choice(list(body.keys()))
    action = random.choice(["drop", "wrong_type", "null_out"])
    if action == "drop":
        del body[key]
    elif action == "wrong_type":
        body[key] = {"unexpected": "shape"}
    else:
        body[key] = None
    return body


def _build_request_body(spec: RouteSpec, malformed_rate: float) -> tuple[dict | None, bool]:
    variant = random.choice(spec.variants) if spec.variants else None
    request_body = (variant or {}).get("request_body_json")
    if request_body is None:
        return None, False
    is_malformed = random.random() < malformed_rate
    return (_malform(request_body) if is_malformed else request_body), is_malformed


def run(base_url: str, duration_s: int, malformed_rate: float, rps: float) -> None:
    with get_db_session() as session:
        specs = load_route_specs(session)
    if not specs:
        print("No routes discovered from the KB — nothing to simulate.")
        return

    interval = 1.0 / rps if rps > 0 else 1.0
    deadline = time.monotonic() + duration_s
    sent = 0
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            spec = random.choice(specs)
            path = _concrete_path(spec)
            body, malformed = _build_request_body(spec, malformed_rate)
            try:
                resp = client.request(spec.http_method, f"{base_url}{path}", json=body)
                print(f"{spec.http_method} {path} malformed={malformed} -> {resp.status_code}")
            except httpx.HTTPError as exc:
                print(f"{spec.http_method} {path} request failed: {exc}")
            sent += 1
            time.sleep(interval)
    print(f"Sent {sent} requests to {base_url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("MOCKPROD_BASE_URL", "http://localhost:8100"))
    parser.add_argument("--duration", type=int, default=int(os.environ.get("SIM_DURATION_S", "60")))
    parser.add_argument("--malformed-rate", type=float, default=float(os.environ.get("SIM_MALFORMED_RATE", "0.3")))
    parser.add_argument("--rps", type=float, default=float(os.environ.get("SIM_RPS", "1")))
    args = parser.parse_args()
    run(args.base_url, args.duration, args.malformed_rate, args.rps)
