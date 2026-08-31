import logging
import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .subscriptions import (
    FIXVERIFY_URL, NOTIFICATION_URL, REPORTING_URL, TRIAGE_URL, subscribers_for,
)

log = logging.getLogger(__name__)
app = FastAPI(title="API Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

SERVICES = {
    "reporting": REPORTING_URL,
    "triage": TRIAGE_URL,
    "fixverify": FIXVERIFY_URL,
    "notifications": NOTIFICATION_URL,
}

FORWARD_HEADERS = {"x-user", "x-role", "content-type", "accept"}


@app.get("/health")
async def health():
    """Aggregated health across all services."""
    results = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, base in SERVICES.items():
            try:
                resp = await client.get(f"{base}/health")
                results[name] = "ok" if resp.status_code == 200 else f"http {resp.status_code}"
            except httpx.HTTPError:
                results[name] = "unreachable"
    return {"gateway": "ok", "services": results}


@app.post("/events")
async def event_bus(event: dict):
    """Fan out one event envelope to its subscribers (best-effort, doc 01)."""
    event_type = event.get("event_type", "")
    deliveries = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for url in subscribers_for(event_type):
            try:
                resp = await client.post(url, json=event)
                deliveries[url] = resp.status_code
            except httpx.HTTPError as exc:
                deliveries[url] = f"failed: {type(exc).__name__}"
                log.warning("event %s delivery to %s failed", event_type, url)
    return {"event_type": event_type, "deliveries": deliveries}


@app.api_route(
    "/api/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy(service: str, path: str, request: Request):
    base = SERVICES.get(service)
    if not base:
        return Response(status_code=404, content=f"unknown service '{service}'")
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_HEADERS}
    async with httpx.AsyncClient(timeout=60) as client:
        upstream = await client.request(
            request.method,
            f"{base}/{path}",
            params=request.query_params,
            content=await request.body(),
            headers=headers,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
