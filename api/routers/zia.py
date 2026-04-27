"""ZIA API router."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel

from api.schemas.zia import UrlLookupRequest
from api.dependencies import require_auth, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zia_service import ZIAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
        govcloud=bool(tenant.govcloud),
    )
    client = ZIAClient(auth, tenant.oneapi_base_url)
    return ZIAService(client, tenant_id=tenant.id)


# ------------------------------------------------------------------
# Activation
# ------------------------------------------------------------------

@router.get("/{tenant}/activation/status")
def get_activation_status(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the current ZIA activation status."""
    return _get_service(tenant, user).get_activation_status()


@router.post("/{tenant}/activation/activate")
def activate(tenant: str, user: AuthUser = Depends(require_auth)):
    """Activate all pending ZIA configuration changes."""
    try:
        return _get_service(tenant, user).activate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories")
def list_url_categories(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL categories (lite)."""
    return _get_service(tenant, user).list_url_categories()


@router.post("/{tenant}/url-lookup")
def url_lookup(tenant: str, req: UrlLookupRequest, user: AuthUser = Depends(require_auth)):
    """Look up category classifications for a list of URLs."""
    try:
        return _get_service(tenant, user).url_lookup(req.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Filtering Rules
# ------------------------------------------------------------------

@router.get("/{tenant}/url-filtering-rules")
def list_url_filtering_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all URL filtering rules."""
    return _get_service(tenant, user).list_url_filtering_rules()


@router.get("/{tenant}/url-filtering-rules/{rule_id}")
def get_url_filtering_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    """Get a single URL filtering rule by ID."""
    try:
        svc = _get_service(tenant, user)
        return svc.client.get_url_filtering_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Users / Locations / Departments / Groups
# ------------------------------------------------------------------

@router.get("/{tenant}/users")
def list_users(tenant: str, name: str = None, user: AuthUser = Depends(require_auth)):
    """List ZIA users, optionally filtered by name."""
    return _get_service(tenant, user).list_users(name=name)


@router.get("/{tenant}/locations")
def list_locations(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA locations (lite)."""
    return _get_service(tenant, user).list_locations()


@router.get("/{tenant}/departments")
def list_departments(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA departments."""
    return _get_service(tenant, user).list_departments()


@router.get("/{tenant}/groups")
def list_groups(tenant: str, user: AuthUser = Depends(require_auth)):
    """List ZIA groups."""
    return _get_service(tenant, user).list_groups()


# ------------------------------------------------------------------
# Allow / Deny Lists
# ------------------------------------------------------------------

@router.get("/{tenant}/allowlist")
def get_allowlist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA allowlist (whitelist URLs)."""
    return _get_service(tenant, user).get_allowlist()


@router.get("/{tenant}/denylist")
def get_denylist(tenant: str, user: AuthUser = Depends(require_auth)):
    """Get the ZIA denylist (blacklist URLs)."""
    return _get_service(tenant, user).get_denylist()


class AllowlistUpdateRequest(BaseModel):
    whitelistUrls: List[str]


class DenylistUpdateRequest(BaseModel):
    blacklistUrls: List[str]


@router.put("/{tenant}/allowlist")
def update_allowlist(tenant: str, body: AllowlistUpdateRequest, user: AuthUser = Depends(require_auth)):
    """Replace the ZIA allowlist."""
    try:
        return _get_service(tenant, user).update_allowlist(body.whitelistUrls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/denylist")
def update_denylist(tenant: str, body: DenylistUpdateRequest, user: AuthUser = Depends(require_auth)):
    """Replace the ZIA denylist."""
    try:
        return _get_service(tenant, user).update_denylist(body.blacklistUrls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Categories — CRUD
# ------------------------------------------------------------------

@router.get("/{tenant}/url-categories/{category_id}")
def get_url_category(tenant: str, category_id: str, user: AuthUser = Depends(require_auth)):
    """Get a single URL category by ID."""
    try:
        return _get_service(tenant, user).get_url_category(category_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/url-categories")
def create_url_category(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Create a custom URL category."""
    try:
        return _get_service(tenant, user).create_url_category(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/url-categories/{category_id}")
def update_url_category(tenant: str, category_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Update a custom URL category."""
    try:
        return _get_service(tenant, user).update_url_category(category_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CategoryUrlsRequest(BaseModel):
    urls: List[str]


@router.post("/{tenant}/url-categories/{category_id}/urls")
def add_urls_to_category(tenant: str, category_id: str, body: CategoryUrlsRequest, user: AuthUser = Depends(require_auth)):
    """Add URLs to a custom URL category."""
    try:
        return _get_service(tenant, user).add_urls_to_category(category_id, body.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/url-categories/{category_id}/urls")
def remove_urls_from_category(tenant: str, category_id: str, body: CategoryUrlsRequest, user: AuthUser = Depends(require_auth)):
    """Remove URLs from a custom URL category."""
    try:
        return _get_service(tenant, user).remove_urls_from_category(category_id, body.urls)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/url-categories/{category_id}")
def delete_url_category(tenant: str, category_id: str, user: AuthUser = Depends(require_auth)):
    """Delete a custom URL category."""
    try:
        _get_service(tenant, user).delete_url_category(category_id)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# URL Filtering Rules — CRUD + state toggle
# ------------------------------------------------------------------

@router.post("/{tenant}/url-filtering-rules")
def create_url_filtering_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Create a URL filtering rule."""
    try:
        return _get_service(tenant, user).create_url_filtering_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/url-filtering-rules/{rule_id}")
def update_url_filtering_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Update a URL filtering rule."""
    try:
        return _get_service(tenant, user).update_url_filtering_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/url-filtering-rules/{rule_id}")
def delete_url_filtering_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    """Delete a URL filtering rule."""
    try:
        _get_service(tenant, user).delete_url_filtering_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RuleStateRequest(BaseModel):
    state: str


@router.patch("/{tenant}/url-filtering-rules/{rule_id}/state")
def patch_url_filtering_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    """Toggle the enabled/disabled state of a URL filtering rule."""
    try:
        svc = _get_service(tenant, user)
        rule = svc.client.get_url_filtering_rule(rule_id)
        rule["state"] = body.state
        return svc.update_url_filtering_rule(rule_id, rule)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# ZIA Users — CRUD
# ------------------------------------------------------------------

@router.get("/{tenant}/users/{user_id}")
def get_zia_user(tenant: str, user_id: str, user: AuthUser = Depends(require_auth)):
    """Get a single ZIA user by ID."""
    try:
        return _get_service(tenant, user).get_user(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/users")
def create_zia_user(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Create a ZIA user."""
    try:
        return _get_service(tenant, user).create_user(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/users/{user_id}")
def update_zia_user(tenant: str, user_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    """Update a ZIA user."""
    try:
        return _get_service(tenant, user).update_user(user_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/users/{user_id}")
def delete_zia_user(tenant: str, user_id: str, user: AuthUser = Depends(require_auth)):
    """Delete a ZIA user."""
    try:
        _get_service(tenant, user).delete_user(user_id)
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Firewall Policy
# ------------------------------------------------------------------

@router.get("/{tenant}/firewall-rules")
def list_firewall_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_firewall_rules()


@router.get("/{tenant}/firewall-rules/export-csv")
def export_firewall_rules_csv(tenant: str, user: AuthUser = Depends(require_auth)):
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from services.config_service import get_tenant
    from services.zia_firewall_service import export_rules_to_csv, CSV_FIELDNAMES
    from api.dependencies import check_tenant_access

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    try:
        rows = export_rules_to_csv(t.id)
        filtered = [r for r in rows if str(r.get("order", "")).isdigit() and int(r["order"]) > 0]

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filtered)
        content = output.getvalue()

        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=\"firewall_rules.csv\""},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/firewall-rules/sync-csv")
def sync_firewall_rules_csv(
    tenant: str,
    file: UploadFile = File(...),
    user: AuthUser = Depends(require_auth),
):
    import tempfile
    import os
    from services.config_service import get_tenant, decrypt_secret
    from services.zia_firewall_service import parse_csv, classify_sync, sync_rules
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from api.dependencies import check_tenant_access

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(file.file.read())
            tmp_path = tmp.name

        try:
            rows = parse_csv(tmp_path)
        finally:
            os.unlink(tmp_path)

        auth = ZscalerAuth(
            t.zidentity_base_url,
            t.client_id,
            decrypt_secret(t.client_secret_enc),
            govcloud=bool(t.govcloud),
        )
        client = ZIAClient(auth, t.oneapi_base_url)

        classification = classify_sync(t.id, rows)
        result = sync_rules(client, t.id, classification)

        from services.zia_service import ZIAService
        ZIAService(client, tenant_id=t.id)._reimport(["firewall_rule"])

        return {
            "created": result.created,
            "updated": result.updated,
            "deleted": result.deleted,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant}/firewall-rules/{rule_id}")
def get_firewall_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).get_firewall_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/firewall-rules")
def create_firewall_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).create_firewall_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/firewall-rules/{rule_id}")
def update_firewall_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).update_firewall_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/firewall-rules/{rule_id}")
def delete_firewall_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        _get_service(tenant, user).delete_firewall_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{tenant}/firewall-rules/{rule_id}/state")
def patch_firewall_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_firewall_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# SSL Inspection
# ------------------------------------------------------------------

@router.get("/{tenant}/ssl-inspection-rules")
def list_ssl_inspection_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_ssl_inspection_rules()


@router.get("/{tenant}/ssl-inspection-rules/{rule_id}")
def get_ssl_inspection_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).get_ssl_inspection_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/ssl-inspection-rules")
def create_ssl_inspection_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).create_ssl_inspection_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/ssl-inspection-rules/{rule_id}")
def update_ssl_inspection_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).update_ssl_inspection_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/ssl-inspection-rules/{rule_id}")
def delete_ssl_inspection_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        _get_service(tenant, user).delete_ssl_inspection_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{tenant}/ssl-inspection-rules/{rule_id}/state")
def patch_ssl_inspection_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_ssl_inspection_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Traffic Forwarding
# ------------------------------------------------------------------

@router.get("/{tenant}/forwarding-rules")
def list_forwarding_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_forwarding_rules()


@router.get("/{tenant}/forwarding-rules/{rule_id}")
def get_forwarding_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).get_forwarding_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/forwarding-rules")
def create_forwarding_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).create_forwarding_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/forwarding-rules/{rule_id}")
def update_forwarding_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).update_forwarding_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/forwarding-rules/{rule_id}")
def delete_forwarding_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        _get_service(tenant, user).delete_forwarding_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{tenant}/forwarding-rules/{rule_id}/state")
def patch_forwarding_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_forwarding_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Firewall DNS Filter Rules
# ------------------------------------------------------------------

@router.get("/{tenant}/firewall-dns-rules")
def list_firewall_dns_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_firewall_dns_rules()


@router.patch("/{tenant}/firewall-dns-rules/{rule_id}/state")
def patch_firewall_dns_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_firewall_dns_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# Firewall IPS Rules
# ------------------------------------------------------------------

@router.get("/{tenant}/firewall-ips-rules")
def list_firewall_ips_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_firewall_ips_rules()


@router.patch("/{tenant}/firewall-ips-rules/{rule_id}/state")
def patch_firewall_ips_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_firewall_ips_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# DLP
# ------------------------------------------------------------------

@router.get("/{tenant}/dlp-web-rules/{rule_id}")
def get_dlp_web_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).get_dlp_web_rule(rule_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/dlp-web-rules")
def create_dlp_web_rule(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).create_dlp_web_rule(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/dlp-web-rules/{rule_id}")
def update_dlp_web_rule(tenant: str, rule_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).update_dlp_web_rule(rule_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/dlp-web-rules/{rule_id}")
def delete_dlp_web_rule(tenant: str, rule_id: str, user: AuthUser = Depends(require_auth)):
    try:
        _get_service(tenant, user).delete_dlp_web_rule(rule_id, rule_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{tenant}/dlp-web-rules/{rule_id}/state")
def patch_dlp_web_rule_state(
    tenant: str, rule_id: str, body: RuleStateRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).toggle_dlp_web_rule(rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant}/dlp-engines")
def list_dlp_engines(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_dlp_engines()


@router.get("/{tenant}/dlp-engines/{engine_id}")
def get_dlp_engine(tenant: str, engine_id: str, user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).get_dlp_engine(engine_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/dlp-engines")
def create_dlp_engine(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).create_dlp_engine(body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/dlp-engines/{engine_id}")
def update_dlp_engine(tenant: str, engine_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    try:
        return _get_service(tenant, user).update_dlp_engine(engine_id, body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/dlp-engines/{engine_id}")
def delete_dlp_engine(tenant: str, engine_id: str, user: AuthUser = Depends(require_auth)):
    try:
        _get_service(tenant, user).delete_dlp_engine(engine_id, engine_name="")
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class DlpDictionaryConfidenceRequest(BaseModel):
    confidenceThreshold: str


@router.patch("/{tenant}/dlp-dictionaries/{dict_id}/confidence")
def patch_dlp_dictionary_confidence(
    tenant: str, dict_id: str, body: DlpDictionaryConfidenceRequest, user: AuthUser = Depends(require_auth)
):
    try:
        return _get_service(tenant, user).update_dlp_dictionary_confidence(dict_id, body.confidenceThreshold)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant}/dlp-dictionaries")
def list_dlp_dictionaries(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_dlp_dictionaries()


@router.get("/{tenant}/dlp-web-rules")
def list_dlp_web_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_dlp_web_rules()


# ------------------------------------------------------------------
# Cloud App Controls
# ------------------------------------------------------------------

@router.get("/{tenant}/cloud-app-settings")
def list_cloud_app_settings(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_cloud_app_settings()

@router.get("/{tenant}/cloud-app-policies")
def list_cloud_app_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_cloud_app_policies()

@router.get("/{tenant}/cloud-app-control-rules")
def list_cloud_app_control_rules(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_cloud_app_control_rules()

@router.get("/{tenant}/tenancy-restriction-profiles")
def list_tenancy_restriction_profiles(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_tenancy_restriction_profiles()

@router.get("/{tenant}/cloud-app-instances")
def list_cloud_app_instances(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).list_cloud_app_instances()

@router.patch("/{tenant}/cloud-app-control-rules/{rule_type}/{rule_id}/state")
def patch_cloud_app_rule_state(
    tenant: str,
    rule_type: str,
    rule_id: str,
    body: RuleStateRequest,
    user: AuthUser = Depends(require_auth),
):
    try:
        return _get_service(tenant, user).toggle_cloud_app_rule(rule_type, rule_id, body.state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------------
# Config Snapshots
# ------------------------------------------------------------------

@router.get("/{tenant}/snapshots")
def list_snapshots(tenant: str, product: str = "ZIA", user: AuthUser = Depends(require_auth)):
    from services.config_service import get_tenant
    from services.snapshot_service import list_snapshots as _list
    from db.database import get_session
    from api.dependencies import check_tenant_access

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    with get_session() as session:
        snaps = _list(t.id, product.upper(), session)
        return [
            {
                "id": s.id,
                "label": s.comment,
                "product": s.product,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "resource_count": s.resource_count,
            }
            for s in snaps
        ]


class SnapshotCreateRequest(BaseModel):
    label: Optional[str] = None
    product: str = "ZIA"


@router.post("/{tenant}/snapshots", status_code=201)
def create_snapshot(
    tenant: str, body: SnapshotCreateRequest, user: AuthUser = Depends(require_auth)
):
    from services.config_service import get_tenant
    from services.snapshot_service import create_snapshot as _create
    from db.database import get_session
    from api.dependencies import check_tenant_access
    from datetime import datetime

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    product = body.product.upper()
    name = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    try:
        with get_session() as session:
            snap = _create(t.id, product, name=name, comment=body.label, session=session)
            return {
                "id": snap.id,
                "label": snap.comment,
                "product": snap.product,
                "created_at": snap.created_at.isoformat() if snap.created_at else None,
                "resource_count": snap.resource_count,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/snapshots/{snapshot_id}", status_code=204)
def delete_snapshot(
    tenant: str, snapshot_id: int, user: AuthUser = Depends(require_auth)
):
    from services.config_service import get_tenant
    from services.snapshot_service import delete_snapshot as _delete
    from db.database import get_session
    from api.dependencies import check_tenant_access

    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    try:
        with get_session() as session:
            _delete(snapshot_id, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
