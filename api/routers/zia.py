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
        gov_tier=tenant.gov_cloud_tier,
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
            gov_tier=t.gov_cloud_tier,
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


# ------------------------------------------------------------------
# Snapshot restore
#
# Restores the tenant to a snapshot taken from that same tenant. Distinct
# from POST /tenants/{id}/snapshots/apply, which pushes one tenant's snapshot
# onto a *different* tenant and never deletes: a restore is only a restore if
# resources created since the snapshot are removed.
#
# Mirrors the TUI flow in cli/menus/snapshots_menu.py:216.
# ------------------------------------------------------------------

def _load_zia_snapshot(tenant_id: int, snapshot_id: int) -> dict:
    """Load a ZIA snapshot belonging to this tenant, or 404."""
    from db.database import get_session
    from db.models import RestorePoint

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=snapshot_id, tenant_id=tenant_id, product="ZIA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return {
            "name": snap.name,
            "comment": snap.comment,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "resource_count": snap.resource_count,
            "resources": snap.snapshot["resources"],
        }


@router.post("/{tenant}/snapshots/{snapshot_id}/restore/preview", status_code=202)
def preview_snapshot_restore(
    tenant: str, snapshot_id: int, user: AuthUser = Depends(require_auth)
):
    """Classify a snapshot restore without writing. Returns a job_id.

    Backgrounded because classification runs a full live import first.
    """
    import threading
    from api.jobs import store
    from services.zia_push_service import ZIAPushService

    svc = _get_service(tenant, user)
    snap = _load_zia_snapshot(svc.tenant_id, snapshot_id)
    job_id = store.create()

    def run():
        try:
            service = ZIAPushService(svc.client, tenant_id=svc.tenant_id)

            def on_import_progress(resource_type: str, done: int, total: int):
                store.append(job_id, {
                    "type": "progress", "phase": "import",
                    "resource_type": resource_type, "done": done, "total": total,
                })

            dry_run = service.classify_baseline(
                {"product": "ZIA", "resources": snap["resources"]},
                import_progress_callback=on_import_progress,
            )
            # Must follow classify_baseline: it imports live state into the DB
            # that classify_snapshot_deletes then reads.
            delete_candidates = service.classify_snapshot_deletes(snap["resources"])

            creates, updates, _ = dry_run.changes_by_action()
            store.complete(job_id, {
                "snapshot_name": snap["name"],
                "snapshot_comment": snap["comment"],
                "snapshot_created": snap["created_at"],
                "snapshot_resource_count": snap["resource_count"],
                "creates": dry_run.create_count,
                "updates": dry_run.update_count,
                "deletes": len(delete_candidates),
                "skips": dry_run.skip_count,
                "items": (
                    [{"action": "create", "resource_type": rt, "name": n} for rt, n in creates]
                    + [{"action": "update", "resource_type": rt, "name": n} for rt, n in updates]
                    + [{"action": "delete", "resource_type": r.resource_type, "name": r.name}
                       for r in delete_candidates]
                ),
            })
        except Exception as exc:
            store.fail(job_id, str(exc))

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


class SnapshotRestoreRequest(BaseModel):
    delete_extras: bool = True   # remove resources absent from the snapshot
    remediate: bool = True       # re-push anything the verify pass finds missing
    activate: bool = False       # activate remaining changes when the restore finishes


@router.post("/{tenant}/snapshots/{snapshot_id}/restore", status_code=202)
def restore_snapshot(
    tenant: str,
    snapshot_id: int,
    body: Optional[SnapshotRestoreRequest] = None,
    user: AuthUser = Depends(require_auth),
):
    """Restore this tenant to one of its own snapshots. Returns a job_id.

    `delete_extras` defaults to True: resources created since the snapshot are
    removed, which is what makes this a restore rather than a merge. Call the
    preview endpoint first to show the user what that covers.
    """
    import threading
    from api.jobs import store
    from services import audit_service
    from services.zia_push_service import ZIAPushService, _PushCancelled

    body = body or SnapshotRestoreRequest()
    svc = _get_service(tenant, user)
    snap = _load_zia_snapshot(svc.tenant_id, snapshot_id)
    job_id = store.create()

    def run():
        service = ZIAPushService(svc.client, tenant_id=svc.tenant_id)
        baseline = {"product": "ZIA", "resources": snap["resources"]}
        counters: Dict[str, int] = {}

        def on_import_progress(resource_type: str, done: int, total: int, phase: str = "import"):
            store.append(job_id, {
                "type": "progress", "phase": phase,
                "resource_type": resource_type, "done": done, "total": total,
            })

        def push_progress(phase: str):
            def cb(_pass_num, resource_type, record):
                counters[phase] = counters.get(phase, 0) + 1
                store.append(job_id, {
                    "type": "progress", "phase": phase,
                    "resource_type": resource_type, "name": record.name,
                    "status": record.status, "done": counters[phase],
                })
            return cb

        def delete_progress(_pass_num, resource_type, record):
            counters["delete"] = counters.get("delete", 0) + 1
            store.append(job_id, {
                "type": "progress", "phase": "delete",
                "resource_type": resource_type, "name": record.name,
                "status": record.status, "done": counters["delete"],
            })

        stop_fn = lambda: store.is_cancel_requested(job_id)

        try:
            dry_run = service.classify_baseline(
                baseline, import_progress_callback=on_import_progress
            )
            delete_candidates = (
                service.classify_snapshot_deletes(snap["resources"])
                if body.delete_extras else []
            )

            push_records: List[Any] = []
            try:
                if dry_run.create_count or dry_run.update_count:
                    push_records = service.push_classified(
                        dry_run, progress_callback=push_progress("push"), stop_fn=stop_fn
                    )
            except _PushCancelled as exc:
                rollback = service.rollback_pushed(exc.pushed_records)
                store.complete(job_id, {
                    "cancelled": True,
                    "rolled_back": sum(
                        1 for r in rollback
                        if r.status in ("rollback_deleted", "rollback_restored")
                    ),
                    "rollback_failed": sum(
                        1 for r in rollback if r.status.startswith("rollback_failed")
                    ),
                })
                return

            # Verify pass 1 — creates and updates.
            discrepancies: List[dict] = []
            if push_records:
                try:
                    verify1 = service.verify_push(
                        baseline,
                        import_progress_callback=lambda rt, d, t: on_import_progress(
                            rt, d, t, phase="verify"),
                    )
                except Exception as exc:
                    store.append(job_id, {"type": "warning",
                                          "message": f"Verify pass 1 failed: {exc}"})
                    verify1 = None

                if verify1 is not None:
                    v_creates, v_updates, v_deletes = verify1.changes_by_action()
                    # Resources queued for deletion are expected to still be
                    # present — deletes have not run yet.
                    pending = {(r.resource_type, r.name) for r in delete_candidates}
                    v_deletes = [(rt, n) for rt, n in v_deletes if (rt, n) not in pending]
                    discrepancies = (
                        [{"issue": "not_created", "resource_type": rt, "name": n}
                         for rt, n in v_creates]
                        + [{"issue": "config_mismatch", "resource_type": rt, "name": n}
                           for rt, n in v_updates]
                        + [{"issue": "not_deleted", "resource_type": rt, "name": n}
                           for rt, n in v_deletes]
                    )
                    if discrepancies and body.remediate:
                        push_records += service.push_classified(
                            verify1, progress_callback=push_progress("remediate")
                        )

            # Deletes.
            delete_records: List[Any] = []
            deleted = 0
            if delete_candidates:
                delete_records = service.execute_deletes(
                    delete_candidates, progress_callback=delete_progress
                )
                deleted = sum(1 for r in delete_records if r.is_deleted)

                # Deletes are not live until activated, and verify pass 2 reads
                # live state — without this it reports every delete as failed.
                if deleted:
                    store.append(job_id, {"type": "progress", "phase": "activate",
                                          "message": "Activating deletions..."})
                    try:
                        svc.client.activate()
                    except Exception as exc:
                        store.append(job_id, {
                            "type": "warning",
                            "message": f"Activation after deletes failed: {exc}",
                        })

            # Verify pass 2 — deletions.
            still_present: List[dict] = []
            if delete_candidates:
                try:
                    still = service.verify_deleted(
                        delete_candidates,
                        import_progress_callback=lambda rt, d, t: on_import_progress(
                            rt, d, t, phase="verify"),
                    )
                    still_present = [{"resource_type": r.resource_type, "name": r.name}
                                     for r in still]
                except Exception as exc:
                    store.append(job_id, {"type": "warning",
                                          "message": f"Verify pass 2 failed: {exc}"})

            created = sum(1 for r in push_records if r.is_created)
            updated = sum(1 for r in push_records if r.is_updated)
            failed_items = [
                {"resource_type": r.resource_type, "name": r.name, "reason": r.failure_reason}
                for r in push_records + delete_records if r.is_failed
            ]
            status = "SUCCESS" if not failed_items and not still_present else "PARTIAL"

            activated = False
            if body.activate:
                try:
                    svc.client.activate()
                    activated = True
                except Exception as exc:
                    store.append(job_id, {"type": "warning",
                                          "message": f"Activation failed: {exc}"})

            audit_service.log(
                product="ZIA", operation="restore_snapshot", action="UPDATE",
                status=status, tenant_id=svc.tenant_id,
                resource_type="snapshot", resource_id=str(snapshot_id),
                resource_name=snap["name"],
                details={"created": created, "updated": updated, "deleted": deleted,
                         "failed": len(failed_items), "delete_extras": body.delete_extras},
            )

            store.complete(job_id, {
                "status": status,
                "snapshot_name": snap["name"],
                "created": created,
                "updated": updated,
                "deleted": deleted,
                "failed": len(failed_items),
                "failed_items": failed_items,
                "discrepancies": discrepancies,
                "still_present": still_present,
                "activated": activated,
            })
        except Exception as exc:
            store.fail(job_id, str(exc))
            audit_service.log(
                product="ZIA", operation="restore_snapshot", action="UPDATE",
                status="FAILURE", tenant_id=svc.tenant_id,
                resource_type="snapshot", resource_id=str(snapshot_id),
                resource_name=snap["name"], error_message=str(exc),
            )

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


# ------------------------------------------------------------------
# Organization
# ------------------------------------------------------------------

@router.get("/{tenant}/sub-clouds")
def get_sub_clouds(tenant: str, user: AuthUser = Depends(require_auth)):
    """Return subclouds and detected ZIA cloud name; reads from local DB when available."""
    from services.config_service import get_tenant
    from api.dependencies import check_tenant_access
    t = get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)
    try:
        svc = _get_service(tenant, user)
        return {"subclouds": svc.get_sub_clouds(), "zia_cloud": t.zia_cloud or ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{tenant}/org-domains")
def get_org_domains(tenant: str, user: AuthUser = Depends(require_auth)):
    """Return org domains; reads from local DB when available, falls back to live API."""
    try:
        return _get_service(tenant, user).get_org_domains()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ------------------------------------------------------------------
# PAC Files
# ------------------------------------------------------------------

class PacFileCreateRequest(BaseModel):
    name: str
    description: str
    pac_commit_message: str
    domain: Optional[str] = None
    pac_content: str
    pac_verification_status: str = "VERIFY_NOERR"
    pac_version_status: str = "DEPLOYED"


class PacFileUpdateRequest(BaseModel):
    name: str
    description: str
    pac_commit_message: str
    pac_content: str
    pac_verification_status: str = "VERIFY_NOERR"
    pac_version_status: str = "DEPLOYED"


class PacFileValidateRequest(BaseModel):
    pac_content: str


@router.get("/{tenant}/pac-files")
def list_pac_files(tenant: str, user: AuthUser = Depends(require_auth)):
    """List PAC files (DB-first; metadata only, no pac_content)."""
    return _get_service(tenant, user).list_pac_files()


@router.get("/{tenant}/pac-files/{pac_id}/versions")
def get_pac_file_versions(tenant: str, pac_id: int, user: AuthUser = Depends(require_auth)):
    """Fetch all versions of a PAC file live from the API (includes pac_content)."""
    try:
        return _get_service(tenant, user).get_pac_file_versions(pac_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/pac-files/validate")
def validate_pac_file(tenant: str, body: PacFileValidateRequest, user: AuthUser = Depends(require_auth)):
    """Validate PAC file content syntax. Does not write to DB or require activation."""
    import logging as _logging
    try:
        return _get_service(tenant, user).validate_pac_file_content(body.pac_content)
    except Exception as e:
        _logging.getLogger(__name__).error("PAC validate error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant}/pac-files")
def create_pac_file(tenant: str, body: PacFileCreateRequest, user: AuthUser = Depends(require_auth)):
    """Create a new PAC file."""
    try:
        config = body.model_dump(exclude_none=True)
        return _get_service(tenant, user).create_pac_file(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{tenant}/pac-files/{pac_id}")
def update_pac_file(tenant: str, pac_id: int, body: PacFileUpdateRequest, user: AuthUser = Depends(require_auth)):
    """Push a new version of a PAC file (clone operation).

    Resolves the current deployed version number automatically before calling
    update_pac_file_content.
    """
    try:
        svc = _get_service(tenant, user)
        # Resolve PAC file from DB list — editable flag lives at the top-level
        # PAC file record, not in per-version objects
        pac_files = svc.list_pac_files()
        pac = next((p for p in pac_files if str(p.get("id", "")) == str(pac_id)), None)
        if pac is None:
            raise HTTPException(status_code=404, detail=f"PAC file {pac_id} not found")
        if pac.get("editable") is False:
            raise HTTPException(status_code=400, detail="This PAC file is not editable")
        # Resolve current deployed version
        versions = svc.get_pac_file_versions(pac_id)
        if not versions:
            raise HTTPException(status_code=404, detail=f"PAC file {pac_id} has no versions")
        deployed = next(
            (v for v in versions if v.get("pacVersionStatus") == "DEPLOYED"),
            None,
        )
        if deployed is None:
            deployed = max(versions, key=lambda v: v.get("pacVersion", 0))
        current_version = deployed["pacVersion"]
        config = body.model_dump(exclude_none=True)
        return svc.update_pac_file_content(pac_id, current_version, config)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant}/pac-files/{pac_id}")
def delete_pac_file(tenant: str, pac_id: int, user: AuthUser = Depends(require_auth)):
    """Delete a PAC file and all its versions."""
    try:
        svc = _get_service(tenant, user)
        # Resolve PAC file from DB list — editable flag lives at the top-level
        # PAC file record, not in per-version objects
        pac_files = svc.list_pac_files()
        pac = next((p for p in pac_files if str(p.get("id", "")) == str(pac_id)), None)
        if pac is None:
            raise HTTPException(status_code=404, detail=f"PAC file {pac_id} not found")
        if pac.get("editable") is False:
            raise HTTPException(status_code=400, detail="This PAC file is not editable")
        svc.delete_pac_file(pac_id, pac.get("name", ""))
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
