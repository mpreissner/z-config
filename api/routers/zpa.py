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

    _CAN_CREATE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "policy_access",
    })
    _CAN_UPDATE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "app_connector", "service_edge",
        "policy_access", "policy_timeout", "policy_forwarding",
        "policy_inspection", "policy_isolation",
    })
    _CAN_DELETE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "app_connector",
        "policy_access", "policy_timeout", "policy_forwarding",
        "policy_inspection", "policy_isolation",
    })

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
                "supported": rtype in _CAN_CREATE,
            })
        # added = in current but not snapshot → action: delete
        for item in rd.added:
            items.append({
                "action": "delete",
                "resource_type": rtype,
                "name": item.get("name") or item["id"],
                "id": item["id"],
                "supported": rtype in _CAN_DELETE,
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
                "supported": rtype in _CAN_UPDATE,
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
    from services import audit_service
    from services.snapshot_service import compute_diff, get_snapshot_data_current

    svc = _get_service(tenant, user)

    with get_session() as session:
        snap = session.query(RestorePoint).filter_by(
            id=snapshot_id, tenant_id=svc.tenant_id, product="ZPA"
        ).first()
        if not snap:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        snap_resources = snap.snapshot["resources"]
        current = get_snapshot_data_current(svc.tenant_id, "ZPA", session)

    diff = compute_diff(snap_resources, current)
    job_id = store.create()

    # Dependency-ordered list — creates run forward, deletes run in reverse.
    _RTYPE_ORDER = [
        "segment_group", "app_connector_group", "server_group",
        "pra_portal", "user_portal", "application", "pra_console",
        "app_connector", "service_edge",
        "policy_access", "policy_timeout", "policy_forwarding",
        "policy_inspection", "policy_isolation",
    ]

    # Volatile fields stripped from all payloads before sending to the API.
    _PAYLOAD_META = frozenset({
        "id", "creation_time", "modified_time", "modified_by",
        "creationTime", "modifiedTime", "modifiedBy",
        "modifiedAt", "createdAt", "modified_at", "created_at",
    })

    # Extra fields to strip per resource type (beyond meta).
    _TYPE_EXTRA_STRIP: Dict[str, frozenset] = {
        "application":       frozenset({"tcp_port_ranges", "udp_port_ranges"}),
        "policy_access":     frozenset({"policy_set_id"}),
        "policy_timeout":    frozenset({"policy_set_id"}),
        "policy_forwarding": frozenset({"policy_set_id"}),
        "policy_inspection": frozenset({"policy_set_id"}),
        "policy_isolation":  frozenset({"policy_set_id"}),
    }

    _POLICY_TYPE_MAP = {
        "policy_access":     "access",
        "policy_timeout":    "timeout",
        "policy_forwarding": "client_forwarding",
        "policy_inspection": "inspection",
        "policy_isolation":  "isolation",
    }

    _CAN_CREATE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "policy_access",
    })
    _CAN_UPDATE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "app_connector", "service_edge",
        "policy_access", "policy_timeout", "policy_forwarding",
        "policy_inspection", "policy_isolation",
    })
    _CAN_DELETE = frozenset({
        "segment_group", "server_group", "app_connector_group",
        "application", "pra_portal", "user_portal", "pra_console",
        "app_connector",
        "policy_access", "policy_timeout", "policy_forwarding",
        "policy_inspection", "policy_isolation",
    })

    def run():
        client = svc.client
        counts = {"applied": 0, "skipped": 0, "failed": 0}
        result_items: list = []
        diff_by_type = {rd.resource_type: rd for rd in diff.resource_diffs}

        total = sum(
            len(rd.removed) + len(rd.added) + len(rd.modified)
            for rd in diff.resource_diffs
        )
        done = [0]

        # old_snapshot_id → newly created id (for cross-resource ref remapping)
        id_map: Dict[str, str] = {}

        def emit(action: str, rtype: str, name: str, status: str, reason: str = ""):
            done[0] += 1
            store.append(job_id, {
                "type": "progress", "phase": "restore",
                "action": action, "resource_type": rtype,
                "name": name, "done": done[0], "total": total,
            })
            result_items.append({
                "action": action, "resource_type": rtype,
                "name": name, "status": status, "reason": reason,
            })

        def remap_ids(obj: Any) -> Any:
            if not id_map:
                return obj
            if isinstance(obj, dict):
                return {k: remap_ids(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [remap_ids(i) for i in obj]
            if isinstance(obj, str) and obj in id_map:
                return id_map[obj]
            return obj

        def clean_payload(rtype: str, raw: dict, is_create: bool) -> dict:
            strip = set(_PAYLOAD_META)
            if is_create:
                strip.add("id")
            strip |= _TYPE_EXTRA_STRIP.get(rtype, frozenset())
            return remap_ids({k: v for k, v in raw.items() if k not in strip})

        def do_create(rtype: str, old_id: str, raw: dict, name: str) -> None:
            payload = clean_payload(rtype, raw, is_create=True)
            try:
                if rtype == "segment_group":
                    result = client.create_segment_group_full(**payload)
                elif rtype == "server_group":
                    result = client.create_server_group_full(**payload)
                elif rtype == "app_connector_group":
                    result = client.create_connector_group(**payload)
                elif rtype == "application":
                    result = client.create_application(**payload)
                elif rtype == "pra_portal":
                    result = client.create_pra_portal(**payload)
                elif rtype == "user_portal":
                    result = client.create_user_portal(**payload)
                elif rtype == "pra_console":
                    result = client.create_pra_console(**payload)
                elif rtype == "policy_access":
                    kw = dict(payload)
                    ac_name = kw.pop("name", name)
                    ac_action = kw.pop("action", "ALLOW")
                    result = client.create_access_rule(name=ac_name, action=ac_action, **kw)
                else:
                    raise ValueError("unsupported")
                new_id = str(result.get("id", ""))
                if old_id and new_id:
                    id_map[old_id] = new_id
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="CREATE",
                    status="SUCCESS", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_id=new_id, resource_name=name,
                    details={"snapshot_id": snapshot_id},
                )
                counts["applied"] += 1
                emit("create", rtype, name, "applied")
            except Exception as exc:
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="CREATE",
                    status="FAILURE", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_name=name, error_message=str(exc),
                )
                counts["failed"] += 1
                emit("create", rtype, name, "failed", str(exc))

        def do_update(rtype: str, rid: str, raw: dict, name: str) -> None:
            payload = clean_payload(rtype, raw, is_create=False)
            try:
                if rtype == "segment_group":
                    client.update_segment_group(rid, payload)
                elif rtype == "server_group":
                    client.update_server_group(rid, payload)
                elif rtype == "app_connector_group":
                    client.update_connector_group(rid, payload)
                elif rtype == "application":
                    client.update_application(rid, payload)
                elif rtype == "pra_portal":
                    client.update_pra_portal(rid, payload)
                elif rtype == "user_portal":
                    client.update_user_portal(rid, payload)
                elif rtype == "pra_console":
                    client.update_pra_console(rid, payload)
                elif rtype == "app_connector":
                    client.update_connector(rid, payload)
                elif rtype == "service_edge":
                    client.update_service_edge(rid, payload)
                elif rtype in _POLICY_TYPE_MAP:
                    client.update_policy_rule(_POLICY_TYPE_MAP[rtype], rid, payload)
                else:
                    raise ValueError("unsupported")
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="UPDATE",
                    status="SUCCESS", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_id=rid, resource_name=name,
                    details={"snapshot_id": snapshot_id},
                )
                counts["applied"] += 1
                emit("update", rtype, name, "applied")
            except Exception as exc:
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="UPDATE",
                    status="FAILURE", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_id=rid, resource_name=name, error_message=str(exc),
                )
                counts["failed"] += 1
                emit("update", rtype, name, "failed", str(exc))

        def do_delete(rtype: str, rid: str, name: str) -> None:
            try:
                if rtype == "segment_group":
                    client.delete_segment_group(rid)
                elif rtype == "server_group":
                    client.delete_server_group(rid)
                elif rtype == "app_connector_group":
                    client.delete_connector_group(rid)
                elif rtype == "application":
                    client.delete_application(rid)
                elif rtype == "pra_portal":
                    client.delete_pra_portal(rid)
                elif rtype == "user_portal":
                    client.delete_user_portal(rid)
                elif rtype == "pra_console":
                    client.delete_pra_console(rid)
                elif rtype == "app_connector":
                    client.delete_connector(rid)
                elif rtype in _POLICY_TYPE_MAP:
                    client.delete_policy_rule(_POLICY_TYPE_MAP[rtype], rid)
                else:
                    raise ValueError("unsupported")
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="DELETE",
                    status="SUCCESS", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_id=rid, resource_name=name,
                    details={"snapshot_id": snapshot_id},
                )
                counts["applied"] += 1
                emit("delete", rtype, name, "applied")
            except Exception as exc:
                audit_service.log(
                    product="ZPA", operation="restore_snapshot", action="DELETE",
                    status="FAILURE", tenant_id=svc.tenant_id, resource_type=rtype,
                    resource_id=rid, resource_name=name, error_message=str(exc),
                )
                counts["failed"] += 1
                emit("delete", rtype, name, "failed", str(exc))

        # ── Phase 1: Deletes (reverse dependency order) ────────────────────────
        for rtype in reversed(_RTYPE_ORDER):
            rd = diff_by_type.get(rtype)
            if not rd:
                continue
            # rd.added = in current but not in snapshot → DELETE
            for item in rd.added:
                name = item.get("name") or item["id"]
                rid = item["id"]
                if rtype in _CAN_DELETE:
                    do_delete(rtype, rid, name)
                else:
                    counts["skipped"] += 1
                    emit("delete", rtype, name, "manual", "delete not supported for this resource type")

        # ── Phase 2: Creates (forward dependency order, track id_map) ──────────
        for rtype in _RTYPE_ORDER:
            rd = diff_by_type.get(rtype)
            if not rd:
                continue
            # rd.removed = in snapshot but not in current → CREATE
            for item in rd.removed:
                name = item.get("name") or item["id"]
                old_id = item["id"]
                if rtype in _CAN_CREATE:
                    do_create(rtype, old_id, item["raw_config"], name)
                else:
                    counts["skipped"] += 1
                    emit("create", rtype, name, "manual", "create not supported for this resource type")

        # ── Phase 3: Updates (forward dependency order) ────────────────────────
        for rtype in _RTYPE_ORDER:
            rd = diff_by_type.get(rtype)
            if not rd:
                continue
            # rd.modified = in both but config differs → UPDATE to snapshot state
            for item in rd.modified:
                name = item.get("name") or item["id"]
                rid = item["id"]
                if rtype in _CAN_UPDATE:
                    do_update(rtype, rid, item["old_config"], name)
                else:
                    counts["skipped"] += 1
                    emit("update", rtype, name, "manual", "update not supported for this resource type")

        # ── Post-restore sync: re-import affected resource types ───────────────
        affected_types = [
            rtype for rtype in _RTYPE_ORDER
            if rtype in diff_by_type
        ]
        if affected_types:
            store.append(job_id, {"type": "progress", "phase": "sync",
                                  "message": "Syncing local DB..."})
            try:
                from services.zpa_import_service import ZPAImportService
                ZPAImportService(client, svc.tenant_id).run(
                    resource_types=affected_types
                )
            except Exception:
                pass  # sync is best-effort; restore result is already recorded

        store.complete(job_id, {
            "applied": counts["applied"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "items": result_items,
        })

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


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
