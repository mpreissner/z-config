import asyncio
import os
import signal
import threading
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.dependencies import require_admin, AuthUser
from api.jobs import store
from services import ssl_service
from services.ssl_service import SSLValidationError

router = APIRouter()


def _require_container_mode() -> None:
    if os.environ.get("ZS_CONTAINER_MODE") != "1":
        raise HTTPException(status_code=503, detail="ssl_container_only")


async def _delayed_restart() -> None:
    await asyncio.sleep(2)
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/api/v1/system/ssl/upload", tags=["System"])
async def upload_ssl(
    method: str = Form(...),
    domain: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
    pfx_password: str = Form(default=""),
    pem_text: str = Form(default=""),
    _: AuthUser = Depends(require_admin),
) -> dict:
    _require_container_mode()

    if method not in ("pfx", "pem_file", "pem_paste"):
        raise HTTPException(status_code=422, detail="method must be pfx, pem_file, or pem_paste")
    if method in ("pfx", "pem_file") and file is None:
        raise HTTPException(status_code=422, detail="file is required for pfx and pem_file methods")
    if method == "pem_paste" and not pem_text.strip():
        raise HTTPException(status_code=422, detail="pem_text is required for pem_paste method")

    try:
        if method == "pfx":
            bundle = ssl_service.process_pfx(await file.read(), pfx_password, domain)
        elif method == "pem_file":
            bundle = ssl_service.process_pem_bytes(await file.read(), domain)
        else:
            bundle = ssl_service.process_pem_text(pem_text, domain)
        ssl_service.save_bundle(bundle, domain)
    except SSLValidationError as e:
        return JSONResponse(status_code=400, content={"detail": e.code, "message": str(e)})

    asyncio.create_task(_delayed_restart())
    return {"status": "restarting", "domain": domain}


@router.get("/api/v1/system/ssl/status", tags=["System"])
def ssl_status(_: AuthUser = Depends(require_admin)) -> dict:
    s = ssl_service.get_status()
    return {
        "active": s.active,
        "mode": s.mode,
        "domain": s.domain,
        "subject": s.subject,
        "sans": s.sans,
        "not_before": s.not_before,
        "not_after": s.not_after,
        "days_until_expiry": s.days_until_expiry,
    }


@router.delete("/api/v1/system/ssl", tags=["System"])
async def remove_ssl(_: AuthUser = Depends(require_admin)) -> dict:
    _require_container_mode()
    ssl_service.remove_ssl()
    asyncio.create_task(_delayed_restart())
    return {"status": "restarting"}


# ── Let's Encrypt (ACME dns-01 over Cloudflare) ────────────────────────────────

class LetsEncryptConfig(BaseModel):
    domain: str
    email: str
    staging: bool = False
    auto_renew: bool = True
    # Blank means "keep the token already on file" — the UI sends an empty box
    # when the admin did not retype it.
    cf_api_token: str = ""


@router.get("/api/v1/system/ssl/letsencrypt", tags=["System"])
def letsencrypt_config(_: AuthUser = Depends(require_admin)) -> dict:
    from services import acme_service

    cfg = acme_service.load_config()
    return {
        "domain": cfg.domain,
        "email": cfg.email,
        "staging": cfg.staging,
        "auto_renew": cfg.auto_renew,
        "token_set": cfg.token_set,
        "last_issued": cfg.last_issued,
        "last_error": cfg.last_error,
    }


@router.post("/api/v1/system/ssl/letsencrypt/verify", tags=["System"])
def letsencrypt_verify(body: LetsEncryptConfig, _: AuthUser = Depends(require_admin)) -> dict:
    """Pre-flight the Cloudflare side before spending an issuance attempt.

    Let's Encrypt rate-limits failed validations, so it is worth proving the
    token works and the zone exists before starting a real order.
    """
    from services import acme_service
    from services.cloudflare_dns import CloudflareError

    acme_service.save_config(
        body.domain, body.email, body.staging, body.auto_renew, body.cf_api_token
    )
    try:
        zone_name = acme_service.verify_dns_access()
    except (acme_service.AcmeError, CloudflareError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "zone": zone_name}


@router.post("/api/v1/system/ssl/letsencrypt/issue", tags=["System"])
def letsencrypt_issue(body: LetsEncryptConfig, _: AuthUser = Depends(require_admin)) -> dict:
    """Start an issuance in the background; progress streams over /api/v1/jobs."""
    _require_container_mode()
    from services import acme_service

    acme_service.save_config(
        body.domain, body.email, body.staging, body.auto_renew, body.cf_api_token
    )
    try:
        acme_service.validate_config(acme_service.load_config())
    except acme_service.AcmeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id, created = store.create_unique("ssl:letsencrypt")
    if not created:
        return {"job_id": job_id, "already_running": True}

    def run():
        def log(message: str) -> None:
            store.append(job_id, {"type": "progress", "message": message})

        try:
            result = acme_service.issue(log)
        except Exception as exc:
            acme_service.record_failure(str(exc))
            store.fail(job_id, str(exc))
            return
        store.complete(job_id, result)
        # Only restart once the client has had a moment to read the result off
        # the SSE stream — the socket dies with the process.
        threading.Timer(3.0, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id, "already_running": False}
