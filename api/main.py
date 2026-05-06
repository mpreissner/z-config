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
import secrets

# Ensure repo root is importable when run via uvicorn from repo root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if os.environ.get("ZS_TUI_ONLY") == "1":
    sys.exit(
        "ZS_TUI_ONLY=1 is set. The FastAPI server will not start. "
        "Run: python -m cli.z_config"
    )

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

import pathlib

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import system, zia, zpa
from api.routers import auth as auth_router, tenants as tenants_router, admin as admin_router
from api.routers import zcc as zcc_router, zdx as zdx_router, zid as zid_router
from api.routers import jobs as jobs_router
from api.routers import scheduled_tasks as scheduled_tasks_router
from api.routers import templates as templates_router
from api.auth_utils import decode_token
from api.dependencies import require_auth, AuthUser
from cli.banner import VERSION


def seed_admin_if_needed() -> str | None:
    """Create a default admin account if none exists. Returns the temp password or None."""
    from db.database import get_session
    from db.models import User
    from api.auth_utils import hash_password

    with get_session() as session:
        admin_exists = session.query(User).filter_by(role="admin", is_active=True).first()

    if admin_exists:
        return None

    temp_password = os.environ.get("ADMIN_INITIAL_PASSWORD") or secrets.token_urlsafe(15)
    with get_session() as session:
        session.add(User(
            username="admin",
            role="admin",
            password_hash=hash_password(temp_password),
            force_password_change=True,
            is_active=True,
        ))
    return temp_password


@asynccontextmanager
async def lifespan(app: FastAPI):
    jwt_secret = os.environ.get("JWT_SECRET", "")
    if len(jwt_secret) < 32:
        sys.exit("FATAL: JWT_SECRET must be set and at least 32 characters.")

    from db.database import init_db
    init_db()

    temp_password = seed_admin_if_needed()
    if temp_password:
        print(f"[zs-config] Admin account created. Initial password: {temp_password}", flush=True)

    from services.encryption_service import rotate_key_if_due
    rotate_key_if_due()

    from services.scheduled_task_service import start_scheduler, stop_scheduler
    start_scheduler()

    yield

    stop_scheduler()


class MfaEnrollMiddleware(BaseHTTPMiddleware):
    _EXEMPT = {
        "/api/v1/auth/webauthn/register/begin",
        "/api/v1/auth/webauthn/register/complete",
        "/api/v1/auth/logout", "/api/v1/auth/refresh",
        "/api/v1/auth/login",
        "/health", "/docs", "/openapi.json", "/redoc",
    }

    async def dispatch(self, request, call_next):
        if request.url.path in self._EXEMPT:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = decode_token(auth.removeprefix("Bearer "))
                if payload.get("mfa_enroll"):
                    return JSONResponse({"detail": "mfa_enrollment_required"}, status_code=403)
            except Exception:
                pass
        return await call_next(request)


class ForcePasswordChangeMiddleware(BaseHTTPMiddleware):
    _EXEMPT = {
        "/api/v1/auth/change-password", "/api/v1/auth/login",
        "/api/v1/auth/logout", "/api/v1/auth/refresh",
        "/api/v1/auth/webauthn/authenticate/begin",
        "/api/v1/auth/webauthn/authenticate/complete",
        "/health", "/docs", "/openapi.json", "/redoc",
    }

    async def dispatch(self, request, call_next):
        if request.url.path in self._EXEMPT:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                payload = decode_token(auth.removeprefix("Bearer "))
                if payload.get("fpc"):
                    return JSONResponse({"detail": "password_change_required"}, status_code=403)
            except Exception:
                pass
        return await call_next(request)


app = FastAPI(
    title="Zscaler Management API",
    description=(
        "REST API layer for Zscaler OneAPI automation. "
        "Powers the GUI client — all endpoints mirror the CLI service layer."
    ),
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(MfaEnrollMiddleware)
app.add_middleware(ForcePasswordChangeMiddleware)

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
app.include_router(zcc_router.router, prefix="/api/v1/zcc", tags=["ZCC"])
app.include_router(zdx_router.router, prefix="/api/v1/zdx", tags=["ZDX"])
app.include_router(zid_router.router, prefix="/api/v1/zid", tags=["ZID"])
app.include_router(system.router)
app.include_router(auth_router.router)
app.include_router(tenants_router.router)
app.include_router(admin_router.router)
app.include_router(jobs_router.router)
app.include_router(scheduled_tasks_router.router)
app.include_router(templates_router.router)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "version": VERSION}


@app.get("/api/v1/audit", tags=["System"])
def get_audit_log(
    tenant_id: int = None,
    product: str = None,
    limit: int = 100,
    user: AuthUser = Depends(require_auth),
):
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


# ── Static files and SPA fallback (must be registered last) ─────────────────
# Conditional on api/static/ existing so that bare-metal dev mode works without
# requiring the frontend to be built first.
_STATIC_DIR = pathlib.Path(__file__).parent / "static"

if _STATIC_DIR.exists() and (_STATIC_DIR / "assets").exists():
    # Mount compiled Vite assets (JS/CSS/fonts) — Vite outputs these under assets/
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(str(_STATIC_DIR / "favicon.svg"), media_type="image/svg+xml")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """Catch-all: return index.html for any path not matched by an API router."""
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"detail": "Frontend not built"}, 404
