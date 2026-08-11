"""ZPA API router.

Each endpoint resolves a tenant, builds the ZPA client, and delegates to
the ZPAService layer — the same layer used by the CLI and headless scripts.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from api.schemas.zpa import (
    ApplicationEnabledPatch,
    CertificateRotateRequest,
    ConnectorEnabledPatch,
    ConnectorGroupCreate,
    ConnectorGroupEnabledPatch,
    ConnectorNamePatch,
    PRAConsoleEnabledPatch,
    PRAPortalCreate,
    PRAPortalEnabledPatch,
    ServiceEdgeEnabledPatch,
    UserPortalEnabledPatch,
)
from api.dependencies import require_auth, AuthUser

router = APIRouter()


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zpa_service import ZPAService
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    if not tenant.zpa_customer_id:
        raise HTTPException(status_code=400, detail=f"Tenant '{tenant_name}' has no ZPA Customer ID")
    check_tenant_access(tenant.id, user)

    auth = ZscalerAuth(
        tenant.zidentity_base_url,
        tenant.client_id,
        decrypt_secret(tenant.client_secret_enc),
        govcloud=bool(tenant.govcloud),
        gov_tier=tenant.gov_cloud_tier,
    )
    client = ZPAClient(auth, tenant.zpa_customer_id, tenant.oneapi_base_url)
    return ZPAService(client, tenant_id=tenant.id)


def _get_db_context(tenant_name: str, user: AuthUser):
    """Returns the tenant object for DB-only read endpoints.

    Validates tenant exists and user has access. No ZPAClient needed.
    """
    from services.config_service import get_tenant
    from api.dependencies import check_tenant_access

    tenant = get_tenant(tenant_name)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(tenant.id, user)
    return tenant


def _get_db_service(tenant_name: str, user: AuthUser):
    """Returns a ZPAService with no live client — for DB-only read endpoints.

    Does not require zpa_customer_id and avoids constructing a ZPAClient.
    """
    from services.zpa_service import ZPAService
    tenant = _get_db_context(tenant_name, user)
    return ZPAService(tenant_id=tenant.id)


# ------------------------------------------------------------------
# Certificates
# ------------------------------------------------------------------

@router.get("/{tenant}/certificates")
def list_certificates(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all certificates for a ZPA tenant (DB-first)."""
    return _get_db_service(tenant, user).list_certificates_from_db()


@router.delete("/{tenant}/certificates/{cert_id}")
def delete_certificate(tenant: str, cert_id: str, user: AuthUser = Depends(require_auth)):
    """Delete a certificate by ID."""
    success = _get_service(tenant, user).delete_certificate(cert_id)
    return {"deleted": success}


@router.post("/{tenant}/certificates/rotate")
def rotate_certificate(tenant: str, req: CertificateRotateRequest, user: AuthUser = Depends(require_auth)):
    """Certificate rotation is not supported via the web API. Use the CLI."""
    raise HTTPException(
        status_code=400,
        detail="Certificate rotation is not supported via the web API. Use the CLI (`zs-config`).",
    )


# ------------------------------------------------------------------
# Applications
# NOTE: These endpoints remain live-API calls (not DB-first) because
# the web UI uses them as part of a create/edit form flow that requires
# real-time data. Candidates for DB-first migration in a future branch.
# ------------------------------------------------------------------

@router.get("/{tenant}/applications")
def list_applications(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List application segments (DB-first). Import Config caches BROWSER_ACCESS type."""
    return _get_db_service(tenant, user).list_applications_from_db(q=q)


@router.get("/{tenant}/applications/{app_id}")
def get_application(tenant: str, app_id: str, user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).get_application(app_id)


@router.post("/{tenant}/applications", status_code=201)
def create_application(tenant: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).create_application(**body)


@router.put("/{tenant}/applications/{app_id}")
def update_application(tenant: str, app_id: str, body: Dict[str, Any], user: AuthUser = Depends(require_auth)):
    return _get_service(tenant, user).update_application(app_id, body)


@router.delete("/{tenant}/applications/{app_id}")
def delete_application(tenant: str, app_id: str, user: AuthUser = Depends(require_auth)):
    success = _get_service(tenant, user).delete_application(app_id, app_name=app_id)
    return {"deleted": success}


@router.patch("/{tenant}/applications/{app_id}/enabled")
def patch_application_enabled(
    tenant: str,
    app_id: str,
    body: ApplicationEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    return _get_service(tenant, user).set_application_enabled(app_id, body.enabled)


# ------------------------------------------------------------------
# Reference data (DB-first — for create/edit form dropdowns)
# ------------------------------------------------------------------

@router.get("/{tenant}/segment-groups")
def list_segment_groups(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_db_service(tenant, user).list_segment_groups()


@router.get("/{tenant}/server-groups")
def list_server_groups(tenant: str, user: AuthUser = Depends(require_auth)):
    return _get_db_service(tenant, user).list_server_groups()


# ------------------------------------------------------------------
# App Connectors (DB-first list + mutations)
# ------------------------------------------------------------------

@router.get("/{tenant}/app-connectors")
def list_app_connectors(tenant: str, user: AuthUser = Depends(require_auth)):
    """List all app connectors (DB-first). Run Import Config to populate the cache."""
    return _get_service(tenant, user).list_connectors_from_db()


@router.get("/{tenant}/connectors")
def list_connectors(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all app connectors (DB-first) with optional name search."""
    return _get_service(tenant, user).list_connectors_from_db(q=q)


@router.patch("/{tenant}/connectors/{connector_id}/enabled")
def patch_connector_enabled(
    tenant: str,
    connector_id: str,
    body: ConnectorEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable an app connector."""
    return _get_service(tenant, user).set_connector_enabled(connector_id, body.enabled)


@router.patch("/{tenant}/connectors/{connector_id}/name")
def patch_connector_name(
    tenant: str,
    connector_id: str,
    body: ConnectorNamePatch,
    user: AuthUser = Depends(require_auth),
):
    """Rename an app connector."""
    return _get_service(tenant, user).rename_connector(connector_id, body.name)


@router.delete("/{tenant}/connectors/{connector_id}")
def delete_connector(
    tenant: str,
    connector_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete an app connector."""
    svc = _get_service(tenant, user)
    rows = svc.list_connectors_from_db()  # TODO: test name-lookup-then-delete pattern
    name = next((r.get("name", connector_id) for r in rows if r.get("zpa_id") == connector_id), connector_id)
    svc.delete_connector(connector_id, name)
    return {"deleted": True}


# ------------------------------------------------------------------
# Connector Groups
# ------------------------------------------------------------------

@router.get("/{tenant}/connector-groups")
def list_connector_groups(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all connector groups (DB-first) with optional name search."""
    return _get_service(tenant, user).list_connector_groups_from_db(q=q)


@router.post("/{tenant}/connector-groups", status_code=201)
def create_connector_group(
    tenant: str,
    body: ConnectorGroupCreate,
    user: AuthUser = Depends(require_auth),
):
    """Create a new connector group."""
    return _get_service(tenant, user).create_connector_group(body.name, body.description)


@router.patch("/{tenant}/connector-groups/{group_id}/enabled")
def patch_connector_group_enabled(
    tenant: str,
    group_id: str,
    body: ConnectorGroupEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable a connector group."""
    return _get_service(tenant, user).set_connector_group_enabled(group_id, body.enabled)


@router.delete("/{tenant}/connector-groups/{group_id}")
def delete_connector_group(
    tenant: str,
    group_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete a connector group."""
    svc = _get_service(tenant, user)
    rows = svc.list_connector_groups_from_db()
    name = next((r.get("name", group_id) for r in rows if r.get("zpa_id") == group_id), group_id)
    svc.delete_connector_group(group_id, name)
    return {"deleted": True}


# ------------------------------------------------------------------
# Service Edges (DB-first list + enable/disable)
# ------------------------------------------------------------------

@router.get("/{tenant}/service-edges")
def list_service_edges(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all service edges (DB-first) with optional name search."""
    return _get_service(tenant, user).list_service_edges_from_db(q=q)


@router.patch("/{tenant}/service-edges/{edge_id}/enabled")
def patch_service_edge_enabled(
    tenant: str,
    edge_id: str,
    body: ServiceEdgeEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable a service edge."""
    return _get_service(tenant, user).set_service_edge_enabled(edge_id, body.enabled)


# ------------------------------------------------------------------
# PRA Portals (DB-first list + mutations)
# ------------------------------------------------------------------

@router.get("/{tenant}/pra-portals")
def list_pra_portals(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all PRA portals (DB-first) with optional name search."""
    return _get_service(tenant, user).list_pra_portals_from_db(q=q)


@router.post("/{tenant}/pra-portals", status_code=201)
def create_pra_portal(
    tenant: str,
    body: PRAPortalCreate,
    user: AuthUser = Depends(require_auth),
):
    """Create a new PRA portal."""
    return _get_service(tenant, user).create_pra_portal(
        name=body.name,
        domain=body.domain,
        certificate_id=body.certificate_id,
        enabled=body.enabled,
        description=body.description,
        user_notification_enabled=body.user_notification_enabled,
        user_notification=body.user_notification,
    )


@router.patch("/{tenant}/pra-portals/{portal_id}/enabled")
def patch_pra_portal_enabled(
    tenant: str,
    portal_id: str,
    body: PRAPortalEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable a PRA portal."""
    return _get_service(tenant, user).set_pra_portal_enabled(portal_id, body.enabled)


@router.delete("/{tenant}/pra-portals/{portal_id}")
def delete_pra_portal(
    tenant: str,
    portal_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete a PRA portal."""
    svc = _get_service(tenant, user)
    rows = svc.list_pra_portals_from_db()
    name = next((r.get("name", portal_id) for r in rows if r.get("zpa_id") == portal_id), portal_id)
    svc.delete_pra_portal(portal_id, name)
    return {"deleted": True}


# ------------------------------------------------------------------
# User Portals (DB-first list + mutations)
# ------------------------------------------------------------------

@router.get("/{tenant}/user-portals")
def list_user_portals(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all user portals (DB-first) with optional name search."""
    return _get_db_service(tenant, user).list_user_portals_from_db(q=q)


@router.patch("/{tenant}/user-portals/{portal_id}/enabled")
def patch_user_portal_enabled(
    tenant: str,
    portal_id: str,
    body: UserPortalEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable a user portal."""
    return _get_service(tenant, user).set_user_portal_enabled(portal_id, body.enabled)


@router.delete("/{tenant}/user-portals/{portal_id}")
def delete_user_portal(
    tenant: str,
    portal_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete a user portal."""
    svc = _get_service(tenant, user)
    rows = svc.list_user_portals_from_db()
    name = next((r.get("name", portal_id) for r in rows if r.get("zpa_id") == portal_id), portal_id)
    svc.delete_user_portal(portal_id, name)
    return {"deleted": True}


# ------------------------------------------------------------------
# PRA Consoles (DB-first list + mutations)
# ------------------------------------------------------------------

@router.get("/{tenant}/pra-consoles")
def list_pra_consoles(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List all PRA consoles (DB-first) with optional name search."""
    return _get_db_service(tenant, user).list_pra_consoles_from_db(q=q)


@router.patch("/{tenant}/pra-consoles/{console_id}/enabled")
def patch_pra_console_enabled(
    tenant: str,
    console_id: str,
    body: PRAConsoleEnabledPatch,
    user: AuthUser = Depends(require_auth),
):
    """Enable or disable a PRA console."""
    return _get_service(tenant, user).set_pra_console_enabled(console_id, body.enabled)


@router.delete("/{tenant}/pra-consoles/{console_id}")
def delete_pra_console(
    tenant: str,
    console_id: str,
    user: AuthUser = Depends(require_auth),
):
    """Delete a PRA console."""
    svc = _get_service(tenant, user)
    rows = svc.list_pra_consoles_from_db()
    name = next((r.get("name", console_id) for r in rows if r.get("zpa_id") == console_id), console_id)
    svc.delete_pra_console(console_id, name)
    return {"deleted": True}


# ------------------------------------------------------------------
# Access Policy (DB-first, read-only)
# ------------------------------------------------------------------

@router.get("/{tenant}/access-policy/rules")
def list_access_policy_rules(
    tenant: str,
    q: Optional[str] = None,
    user: AuthUser = Depends(require_auth),
):
    """List all access policy rules (DB-first), sorted by rule_order."""
    return _get_db_service(tenant, user).list_access_policy_rules_from_db(q=q)


@router.get("/{tenant}/access-policy/rules/export.csv")
def export_access_policy_csv(
    tenant: str,
    user: AuthUser = Depends(require_auth),
):
    """Export access policy rules as CSV (DB-first)."""
    csv_data = _get_db_service(tenant, user).export_access_policy_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="access_policy_{tenant}.csv"'},
    )


# ------------------------------------------------------------------
# Config Snapshots (ZPA)
# ------------------------------------------------------------------

@router.get("/{tenant}/snapshots/{snapshot_id}/diff")
def get_zpa_snapshot_diff(
    tenant: str,
    snapshot_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Return the diff between a ZPA snapshot and the current DB state."""
    from db.database import get_session
    from db.models import RestorePoint
    from services.snapshot_service import compute_diff, get_snapshot_data_current
    from services.zpa_push_service import CAN_CREATE, CAN_DELETE, CAN_UPDATE

    t = _get_db_context(tenant, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=snapshot_id, tenant_id=t.id, product="ZPA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_resources = snap.snapshot["resources"]
        snap_label = snap.comment
        snap_created = snap.created_at.isoformat() if snap.created_at else None
        snap_resource_count = snap.resource_count
        current = get_snapshot_data_current(t.id, "ZPA", session)

    diff = compute_diff(snap_resources, current)

    items = []
    for rd in diff.resource_diffs:
        rtype = rd.resource_type
        # removed = in snapshot but not current → action: create
        for item in rd.removed:
            items.append({
                "action": "create",
                "resource_type": rtype,
                "name": item.get("name") or item["id"],
                "id": item["id"],
                "supported": rtype in CAN_CREATE,
            })
        # added = in current but not snapshot → action: delete
        for item in rd.added:
            items.append({
                "action": "delete",
                "resource_type": rtype,
                "name": item.get("name") or item["id"],
                "id": item["id"],
                "supported": rtype in CAN_DELETE,
            })
        # modified = in both but different → action: update
        for item in rd.modified:
            field_names = {fc.field for fc in item["field_changes"]}
            enabled_only = field_names == {"enabled"}
            items.append({
                "action": "update",
                "resource_type": rtype,
                "name": item.get("name") or item["id"],
                "id": item["id"],
                "enabled_only": enabled_only,
                "supported": rtype in CAN_UPDATE,
            })

    creates = sum(1 for i in items if i["action"] == "create")
    updates = sum(1 for i in items if i["action"] == "update")
    deletes = sum(1 for i in items if i["action"] == "delete")

    return {
        "snapshot_id": snapshot_id,
        "snapshot_label": snap_label,
        "created_at": snap_created,
        "resource_count": snap_resource_count,
        "creates": creates,
        "updates": updates,
        "deletes": deletes,
        "items": items,
    }


@router.post("/{tenant}/snapshots/{snapshot_id}/restore", status_code=202)
def restore_zpa_snapshot(
    tenant: str,
    snapshot_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Apply a ZPA snapshot restore in the background. Returns a job_id."""
    import threading
    from api.jobs import store
    from db.database import get_session
    from db.models import RestorePoint
    from services.zpa_push_service import ZPAPushService

    svc = _get_service(tenant, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=snapshot_id, tenant_id=svc.tenant_id, product="ZPA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_resources = snap.snapshot["resources"]

    push = ZPAPushService(svc.client, svc.tenant_id)
    plan = push.classify_restore(snap_resources)
    job_id = store.create()

    def run():
        def on_progress(event: Dict[str, Any]) -> None:
            store.append(job_id, {
                "type": "progress", "phase": "restore",
                "action": event["action"], "resource_type": event["resource_type"],
                "name": event["name"], "done": event["done"], "total": event["total"],
            })

        records = push.push_classified(
            plan,
            progress_callback=on_progress,
            audit_operation="restore_snapshot",
            audit_details={"snapshot_id": snapshot_id},
        )

        if push.affected_types(plan):
            store.append(job_id, {"type": "progress", "phase": "sync",
                                  "message": "Syncing local DB..."})
            push.sync_after_push(plan)

        store.complete(job_id, {
            "applied": sum(1 for r in records if r.is_applied),
            "skipped": sum(1 for r in records if r.is_manual),
            "failed":  sum(1 for r in records if r.is_failed),
            "items":   [r.to_item() for r in records],
        })

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@router.post("/{tenant}/snapshots/{snapshot_id}/restore/preview")
def preview_zpa_snapshot_restore(
    tenant: str,
    snapshot_id: int,
    user: AuthUser = Depends(require_auth),
):
    """Classify a snapshot restore without writing. Returns the proposed changes."""
    from db.database import get_session
    from db.models import RestorePoint
    from services.zpa_push_service import ZPAPushService

    svc = _get_service(tenant, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=snapshot_id, tenant_id=svc.tenant_id, product="ZPA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_resources = snap.snapshot["resources"]

    plan = ZPAPushService(svc.client, svc.tenant_id).classify_restore(snap_resources)
    creates, updates, deletes = plan.changes_by_action()
    return {
        "mode": plan.mode,
        "create_count": plan.create_count,
        "update_count": plan.update_count,
        "delete_count": plan.delete_count,
        "skip_count": plan.skip_count,
        "type_summary": plan.type_summary(),
        "creates": [{"resource_type": t, "name": n} for t, n in creates],
        "updates": [{"resource_type": t, "name": n} for t, n in updates],
        "deletes": [{"resource_type": t, "name": n} for t, n in deletes],
        "skipped": [
            {"resource_type": e.resource_type, "name": e.name,
             "action": e.action, "reason": e.skip_reason}
            for e in plan.skipped
        ],
    }


# ------------------------------------------------------------------
# Identity (DB-first, read-only)
# ------------------------------------------------------------------

@router.get("/{tenant}/saml-attributes")
def list_saml_attributes(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List SAML attributes (DB-first)."""
    return _get_db_service(tenant, user).list_saml_attributes_from_db(q=q)


@router.get("/{tenant}/scim-attributes")
def list_scim_attributes(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List SCIM user attributes (DB-first)."""
    return _get_db_service(tenant, user).list_scim_attributes_from_db(q=q)


@router.get("/{tenant}/scim-groups")
def list_scim_groups(tenant: str, q: Optional[str] = None, user: AuthUser = Depends(require_auth)):
    """List SCIM groups (DB-first)."""
    return _get_db_service(tenant, user).list_scim_groups_from_db(q=q)
