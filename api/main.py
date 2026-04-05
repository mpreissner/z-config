"""FastAPI application — REST API layer for the future GUI client.

This module exposes the same service layer used by the CLI and headless
scripts as a REST API, making it straightforward to build a web or desktop
GUI on top without duplicating any business logic.

Run with:
    uvicorn api.main:app --reload

The auto-generated OpenAPI docs are available at:
    http://localhost:8000/docs
"""

import os
import sys

# Ensure repo root is importable when run via uvicorn from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import zia, zpa


@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.database import init_db
    init_db()
    yield


app = FastAPI(
    title="Zscaler Management API",
    description=(
        "REST API layer for Zscaler OneAPI automation. "
        "Powers the GUI client — all endpoints mirror the CLI service layer."
    ),
    version="1.0.13",
    lifespan=lifespan,
)

# Allow the future GUI (any origin in dev, lock down in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(zpa.router, prefix="/api/v1/zpa", tags=["ZPA"])
app.include_router(zia.router, prefix="/api/v1/zia", tags=["ZIA"])


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "version": "1.0.13"}


@app.get("/api/v1/tenants", tags=["System"])
def list_tenants():
    from services.config_service import list_tenants as _list
    tenants = _list()
    return [
        {
            "id": t.id,
            "name": t.name,
            "zidentity_base_url": t.zidentity_base_url,
            "oneapi_base_url": t.oneapi_base_url,
            "govcloud": t.govcloud,
            "zpa_customer_id": t.zpa_customer_id,
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tenants
    ]


@app.get("/api/v1/audit", tags=["System"])
def get_audit_log(tenant_id: int = None, product: str = None, limit: int = 100):
    from services import audit_service
    logs = audit_service.get_recent(tenant_id=tenant_id, product=product, limit=limit)
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "product": e.product,
            "operation": e.operation,
            "action": e.action,
            "status": e.status,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "resource_name": e.resource_name,
            "details": e.details,
            "error_message": e.error_message,
        }
        for e in logs
    ]
