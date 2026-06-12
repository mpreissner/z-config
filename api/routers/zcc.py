"""ZCC API router."""

import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_auth, require_admin, AuthUser

router = APIRouter()

# Password fields that must never appear in API responses or audit entries.
_PASSWORD_FIELDS = {
    "exitPassword", "zdxDisablePassword", "zdDisablePassword",
    "zpaDisablePassword", "zdpDisablePassword",
}


def _strip_passwords(obj: Any) -> Any:
    """Recursively remove password fields from a dict/list."""
    if isinstance(obj, dict):
        return {k: _strip_passwords(v) for k, v in obj.items() if k not in _PASSWORD_FIELDS}
    if isinstance(obj, list):
        return [_strip_passwords(i) for i in obj]
    return obj


def _as_list(val) -> list:
    """Return val as a list; split comma-separated strings into items."""
    if not val:
        return []
    if isinstance(val, list):
        return [v for v in val if v]
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return [val]


def _mask_to_prefix(mask: str) -> int:
    try:
        return sum(bin(int(p)).count("1") for p in mask.split("."))
    except Exception:
        return 0


def _fetch_pac_bypasses(pac_url: str, timeout: int = 4) -> List[Dict]:
    """Fetch a PAC URL and extract DIRECT bypass rules using regex heuristics.

    Returns a list of {"label": str, "detail": str} items describing bypasses.
    Only looks at uncommented lines to avoid false positives.
    """
    if not pac_url or not pac_url.startswith("http"):
        return []
    # PAC URLs originate from Zscaler cloud configuration — treat as trusted.
    # If this assumption changes, validate that the host resolves to a public IP.
    try:
        req = urllib.request.Request(pac_url, headers={"User-Agent": "zs-config/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []

    # Strip single-line comments to avoid matching commented-out rules
    content_nc = re.sub(r"//[^\n]*", "", content)

    results: List[Dict] = []
    seen: set = set()

    def _add(label: str, detail: str = "") -> None:
        key = label
        if key not in seen:
            seen.add(key)
            results.append({"label": label, "detail": detail})

    # ── 1. RFC1918 / privateIP regex variable pattern ────────────────────────
    # Strategy: find any JS variable assigned a regex literal that contains
    # RFC1918-like prefixes, then confirm that variable.test() is called near DIRECT.
    # e.g.: var privateIP = /^(0|10|127|192\.168|...)\.[0-9.]+$/;
    _rfc_map = {
        "10": "10.0.0.0/8",
        "127": "127.0.0.0/8",
        r"192\.168": "192.168.0.0/16",
        r"172\.1[6789]": "172.16.0.0/12",
        r"172\.2[0-9]": "172.16.0.0/12",
        r"172\.3[01]": "172.16.0.0/12",
        r"169\.254": "169.254.0.0/16",
        r"192\.88\.99": "192.88.99.0/24",
    }
    var_regex_re = re.compile(r"var\s+(\w+)\s*=\s*/([^/\n]{10,})/[gimy]*\s*;")
    for m in var_regex_re.finditer(content_nc):
        varname, regex_body = m.group(1), m.group(2)
        # Only consider regex literals that look like IP prefix filters
        if not re.search(r"\b(192|172|10|127|169)\b", regex_body):
            continue
        # Confirm varname.test(...) appears near a DIRECT return
        test_re = re.compile(rf"\b{re.escape(varname)}\.test\s*\(")
        for tm in test_re.finditer(content_nc):
            ctx = content_nc[tm.start(): min(len(content_nc), tm.end() + 400)]
            if "DIRECT" not in ctx:
                continue
            # Extract alternation parts from the regex body to map to CIDRs
            found: List[str] = []
            cidr_seen_rfc: set = set()
            for pat, cidr in _rfc_map.items():
                if pat in regex_body and cidr not in cidr_seen_rfc:
                    cidr_seen_rfc.add(cidr)
                    found.append(cidr)
            label = "RFC1918 private IPs → DIRECT"
            detail = ", ".join(found) if found else regex_body[:80]
            _add(label, detail)
            break

    # ── 2. isInNet(x, "ip", "mask") → DIRECT ────────────────────────────────
    innet_re = re.compile(
        r'isInNet\s*\([^,)]+,\s*"([0-9.]+)"\s*,\s*"([0-9.]+)"\s*\)'
    )
    for m in innet_re.finditer(content_nc):
        ip, mask = m.group(1), m.group(2)
        ctx_end = min(len(content_nc), m.end() + 300)
        ctx = content_nc[m.start():ctx_end]
        if "DIRECT" not in ctx:
            continue
        prefix = _mask_to_prefix(mask)
        cidr = f"{ip}/{prefix}"
        _add(f"{cidr} → DIRECT", "isInNet rule")

    # ── 3. Explicit host == "..." → DIRECT ───────────────────────────────────
    host_eq_re = re.compile(r'host\s*==\s*"([^"]+)"')
    for m in host_eq_re.finditer(content_nc):
        host = m.group(1)
        ctx_end = min(len(content_nc), m.end() + 200)
        ctx = content_nc[m.start():ctx_end]
        if "DIRECT" in ctx:
            _add(f"{host} → DIRECT", "host match")

    # ── 4. shExpMatch(host, "pattern") → DIRECT (non-example patterns) ───────
    shexp_re = re.compile(r'shExpMatch\s*\(\s*host\s*,\s*"([^"]+)"\s*\)')
    for m in shexp_re.finditer(content_nc):
        pattern = m.group(1)
        if "example" in pattern.lower():
            continue
        ctx_end = min(len(content_nc), m.end() + 200)
        ctx = content_nc[m.start():ctx_end]
        if "DIRECT" in ctx:
            _add(f"{pattern} → DIRECT", "shExpMatch")

    # ── 5. isPlainHostName → DIRECT ──────────────────────────────────────────
    for m in re.finditer(r"isPlainHostName\s*\(", content_nc):
        ctx = content_nc[m.start(): min(len(content_nc), m.end() + 300)]
        if "DIRECT" in ctx:
            _add("Plain hostnames (unqualified) → DIRECT", "isPlainHostName")
            break

    # ── 6. Non-HTTP/S protocols → DIRECT ─────────────────────────────────────
    if re.search(r"url\.substring.*!=.*https?.*DIRECT", content_nc, re.DOTALL):
        _add("Non-HTTP/S protocols → DIRECT", "protocol check")

    return results


def _derive_tunnel_mode(raw_fp: Optional[Dict]) -> str:
    """Derive tunnel mode string from forwarding profile raw_config.

    Handles both camelCase (onNetPolicy from direct HTTP) and snake_case
    (forwarding_profile DB records from the old SDK-based import).
    """
    if not raw_fp:
        return "Unknown"
    actions = (raw_fp.get("forwardingProfileActions") or
               raw_fp.get("forwarding_profile_actions") or [])
    if not actions:
        return "Unknown"
    first = actions[0] if isinstance(actions[0], dict) else {}
    if first.get("enablePacketTunnel") or first.get("enable_packet_tunnel"):
        return "Z-Tunnel 2.0"
    spd = first.get("systemProxyData") or first.get("system_proxy_data") or {}
    if spd.get("enableProxyServer") or spd.get("enable_proxy_server"):
        return "Proxy"
    return "Z-Tunnel 1.0"


def _detect_listening_proxy(raw_fp: Optional[Dict]) -> bool:
    """Return True when 'Redirect Web Traffic to ZCC Listening Proxy' is enabled.

    The actual API field is redirect_web_traffic (snake_case from DB import) or
    redirectWebTraffic (camelCase from direct HTTP). system_proxy is not a reliable
    indicator — it is set to 2 whenever ZT2 is active regardless of LP state.
    """
    if not raw_fp:
        return False
    actions = (raw_fp.get("forwardingProfileActions") or
               raw_fp.get("forwarding_profile_actions") or [])
    if not actions:
        return False
    first = actions[0] if isinstance(actions[0], dict) else {}
    return bool(first.get("redirectWebTraffic") or first.get("redirect_web_traffic"))


def _detect_zpa(raw_fp: Optional[Dict]) -> bool:
    """Return True when the forwarding profile indicates ZPA access is configured.

    Checks forwardingProfileZpaActions (camelCase from direct HTTP) or
    forwarding_profile_zpa_actions (snake_case from legacy SDK import).
    ZPA is active when any action has actionType/action_type that is truthy.
    """
    if not raw_fp:
        return False
    # camelCase ZPA actions (onNetPolicy from direct HTTP)
    for action in (raw_fp.get("forwardingProfileZpaActions") or []):
        if isinstance(action, dict):
            at = action.get("actionType") or action.get("action_type") or 0
            if at and at != 0:
                return True
    # snake_case ZPA actions (legacy forwarding_profile DB record)
    for action in (raw_fp.get("forwarding_profile_zpa_actions") or []):
        if isinstance(action, dict):
            at = action.get("action_type") or action.get("actionType") or 0
            if at and at != 0:
                return True
    return False


def _extract_process_bypasses(raw_policy: Dict) -> List[Dict]:
    """Extract per-OS process-based bypass entries from a web_policy raw_config."""
    platform_keys = {
        "windowsPolicy": "windows",
        "macPolicy": "macos",
        "macosPolicy": "macos",
        "linuxPolicy": "linux",
        "iosPolicy": "ios",
        "androidPolicy": "android",
    }
    bypasses = []
    for pol_key, platform in platform_keys.items():
        sub = raw_policy.get(pol_key)
        if not isinstance(sub, dict):
            continue
        for field_name, field_val in sub.items():
            if "bypass" not in field_name.lower():
                continue
            items = field_val if isinstance(field_val, list) else [field_val]
            for item in items:
                if isinstance(item, dict):
                    proc = item.get("processName") or item.get("process_name") or item.get("name") or str(item)
                    bypasses.append({"processName": proc, "platform": platform})
                elif isinstance(item, str) and item:
                    bypasses.append({"processName": item, "platform": platform})
    return bypasses


def _extract_policy_targets(raw_policy: Dict, field: str) -> List[Dict]:
    """Extract user/group/department targeting objects from a web policy."""
    items = raw_policy.get(field) or []
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        if isinstance(item, dict):
            name = str(
                item.get("name") or item.get("userName") or item.get("groupName") or
                item.get("deptName") or item.get("departmentName") or ""
            )
            id_val = str(
                item.get("id") or item.get("userId") or item.get("groupId") or
                item.get("deptId") or ""
            )
            if name or id_val:
                result.append({"id": id_val, "name": name})
        elif isinstance(item, str) and item:
            result.append({"id": item, "name": item})
    return result


def _build_traffic_profile(
    raw_policy: Dict,
    raw_fp: Optional[Dict],
    zia_pac_file_id: Optional[int] = None,
    zia_pac_file_name: Optional[str] = None,
    predefined_ip_bypasses: Optional[List[Dict]] = None,
    custom_ip_bypasses: Optional[List[Dict]] = None,
    app_service_bypasses: Optional[List[Dict]] = None,
) -> Dict:
    """Pure function: build a TrafficProfile dict from two raw_config dicts."""
    pe = raw_policy.get("policyExtension") or {}

    # Forwarding profile info
    fp_name = raw_fp.get("name") if raw_fp else None
    fp_id = str(raw_policy.get("forwardingProfileId", "")) or None
    tunnel_mode = _derive_tunnel_mode(raw_fp)

    # ZPA and listening-proxy detection
    zpa_enabled = _detect_zpa(raw_fp)
    listening_proxy = _detect_listening_proxy(raw_fp)

    # PAC config
    pac_url = raw_policy.get("pac_url") or raw_policy.get("pacUrl") or None
    fp_pac_url = None
    enable_pac = False
    custom_pac_len = None
    if raw_fp:
        actions = (raw_fp.get("forwardingProfileActions") or
                   raw_fp.get("forwarding_profile_actions") or [])
        if actions and isinstance(actions[0], dict):
            first = actions[0]
            spd = (first.get("systemProxyData") or
                   first.get("system_proxy_data") or {})
            fp_pac_url = (spd.get("pacURL") or spd.get("pac_u_r_l") or
                          spd.get("pac_url") or None)
            enable_pac = bool(spd.get("enablePAC") or spd.get("enable_p_a_c") or
                              spd.get("enable_pac"))
            custom_pac = first.get("customPac") or first.get("custom_pac")
            if custom_pac:
                custom_pac_len = len(str(custom_pac))

    pac = {
        "url": pac_url,
        "profilePacUrl": fp_pac_url,
        "customPacContent": custom_pac_len,
        "enablePac": enable_pac,
        "ziaPacFileId": zia_pac_file_id,
        "ziaPacFileName": zia_pac_file_name,
        # _fetch_pac_bypasses uses blocking urllib — safe here because
        # get_traffic_profile is a sync def, so FastAPI runs it in a thread pool.
        "bypasses": _fetch_pac_bypasses(fp_pac_url) if fp_pac_url else [],
        "appProfileBypasses": _fetch_pac_bypasses(pac_url) if pac_url else [],
    }

    # Port bypasses — sourcePortBasedBypasses may be a list of dicts or a
    # comma-separated string of "port:protocol" tokens (e.g. "3389:*,443:TCP").
    port_bypasses = []
    for pb in _as_list(pe.get("sourcePortBasedBypasses")):
        if isinstance(pb, dict):
            port_bypasses.append({
                "port": str(pb.get("port", "")),
                "protocol": str(pb.get("protocol", pb.get("proto", ""))),
            })
        elif isinstance(pb, str) and pb:
            if ":" in pb:
                port, proto = pb.split(":", 1)
                port_bypasses.append({"port": port.strip(), "protocol": proto.strip()})
            else:
                port_bypasses.append({"port": pb.strip(), "protocol": "*"})

    # VPN gateway bypasses — vpnGateways may be a comma-separated string
    vpn_bypasses = []
    for gw in _as_list(pe.get("vpnGateways")):
        if isinstance(gw, str):
            vpn_bypasses.append({"gateway": gw})
        elif isinstance(gw, dict):
            vpn_bypasses.append({"gateway": gw.get("gateway") or gw.get("domain") or str(gw)})

    # Tunnel routes — ZCC stores these as comma-separated strings, not arrays
    tunnel_routes = []
    for cidr in _as_list(pe.get("packetTunnelIncludeList")):
        tunnel_routes.append({"cidr": cidr, "direction": "include", "ipVersion": "ipv4"})
    for cidr in _as_list(pe.get("packetTunnelExcludeList")):
        tunnel_routes.append({"cidr": cidr, "direction": "exclude", "ipVersion": "ipv4"})
    for cidr in _as_list(pe.get("packetTunnelIncludeListForIPv6")):
        tunnel_routes.append({"cidr": cidr.strip("[]"), "direction": "include", "ipVersion": "ipv6"})
    for cidr in _as_list(pe.get("packetTunnelExcludeListForIPv6")):
        tunnel_routes.append({"cidr": cidr.strip("[]"), "direction": "exclude", "ipVersion": "ipv6"})

    # DNS routes — also comma-separated strings
    dns_routes = []
    for suffix in _as_list(pe.get("packetTunnelDnsIncludeList")):
        dns_routes.append({"suffix": suffix, "direction": "include"})
    for suffix in _as_list(pe.get("packetTunnelDnsExcludeList")):
        dns_routes.append({"suffix": suffix, "direction": "exclude"})

    # Process bypasses extracted from platform sub-policies
    process_bypasses = _extract_process_bypasses(raw_policy)

    # Trusted networks from forwarding profile (camelCase from direct HTTP or snake_case legacy)
    trusted_networks: List[str] = []
    if raw_fp:
        trusted_networks = (raw_fp.get("trustedNetworks") or
                            raw_fp.get("trusted_networks") or [])

    # Policy targeting — users/groups/departments may be empty (means all users)
    device_type = raw_policy.get("device_type") or None
    target_users = _extract_policy_targets(raw_policy, "users")
    target_groups = _extract_policy_targets(raw_policy, "groups")
    target_departments = _extract_policy_targets(raw_policy, "departments")

    # Strip password fields from rawPolicySnippet
    raw_snippet = _strip_passwords(pe)

    # Forwarding profile raw snippet
    raw_fp_snippet = _strip_passwords(raw_fp) if raw_fp else None

    return {
        "policyId": str(raw_policy.get("id", "")),
        "policyName": raw_policy.get("name", ""),
        "active": bool(raw_policy.get("active")),
        "tunnelMode": tunnel_mode,
        "forwardingProfileName": fp_name,
        "forwardingProfileId": fp_id,
        "pac": pac,
        "processBypasses": process_bypasses,
        "portBypasses": port_bypasses,
        "vpnGatewayBypasses": vpn_bypasses,
        "predefinedIpBypasses": predefined_ip_bypasses or [],
        "customIpBypasses": custom_ip_bypasses or [],
        "appServiceBypasses": app_service_bypasses or [],
        "tunnelRoutes": tunnel_routes,
        "dnsRoutes": dns_routes,
        "tunnelZappTraffic": bool(raw_policy.get("tunnelZappTraffic")),
        "trustedNetworks": trusted_networks,
        "zpaEnabled": zpa_enabled,
        "listeningProxy": listening_proxy,
        "deviceType": device_type,
        "targetUsers": target_users,
        "targetGroups": target_groups,
        "targetDepartments": target_departments,
        "rawPolicySnippet": raw_snippet,
        "rawForwardingSnippet": raw_fp_snippet,
    }


def _get_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zcc_client import ZCCClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zcc_service import ZCCService
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
    client = ZCCClient(auth, tenant.oneapi_base_url, tenant.zia_cloud, tenant.zia_tenant_id)
    return ZCCService(client, tenant_id=tenant.id)


def _get_snapshot_service(tenant_name: str, user: AuthUser):
    from lib.auth import ZscalerAuth
    from lib.zcc_client import ZCCClient
    from services.config_service import decrypt_secret, get_tenant
    from services.zcc_snapshot_service import ZCCSnapshotService
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
    client = ZCCClient(auth, tenant.oneapi_base_url, tenant.zia_cloud, tenant.zia_tenant_id)
    return ZCCSnapshotService(client, tenant_id=tenant.id)


class DeviceRemoveRequest(BaseModel):
    udids: List[str]
    os_type: int


class SnapshotCreateRequest(BaseModel):
    label: str
    note: Optional[str] = None


class SnapshotRestoreRequest(BaseModel):
    resource_types: Optional[List[str]] = None
    dry_run: bool = False
    target_tenant: Optional[str] = None


# ------------------------------------------------------------------
# Devices
# ------------------------------------------------------------------

@router.get("/{tenant}/devices")
def list_devices(
    tenant: str,
    username: Optional[str] = None,
    os_type: Optional[int] = None,
    page_size: int = 500,
    user: AuthUser = Depends(require_auth),
):
    rows = _db_resources(tenant, user, "device")
    if username:
        rows = [r for r in rows if (r.get("user") or "").lower().startswith(username.lower())]
    if os_type is not None:
        rows = [r for r in rows if r.get("type") == os_type]
    return rows[:page_size]


@router.delete("/{tenant}/devices/remove")
def remove_devices(
    tenant: str,
    body: DeviceRemoveRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.remove_device(udid_list=body.udids, os_type=body.os_type)


@router.delete("/{tenant}/devices/force-remove")
def force_remove_devices(
    tenant: str,
    body: DeviceRemoveRequest,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.force_remove_device(udid_list=body.udids, os_type=body.os_type)


@router.get("/{tenant}/devices/otp/{udid}")
def get_device_otp(
    tenant: str,
    udid: str,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_service(tenant, user)
    return svc.get_otp(udid=udid)


# ------------------------------------------------------------------
# Configuration resources — DB-first reads
# ------------------------------------------------------------------

def _db_resources(tenant_name: str, user: AuthUser, resource_type: str) -> List[Dict]:
    """Return raw_config dicts from ZCCResource for the given resource_type."""
    from db.database import get_session
    from db.models import ZCCResource
    from api.dependencies import check_tenant_access
    from services.config_service import get_tenant as _get_tenant

    t = _get_tenant(tenant_name)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_name}' not found")
    check_tenant_access(t.id, user)

    with get_session() as session:
        rows = (
            session.query(ZCCResource)
            .filter_by(tenant_id=t.id, resource_type=resource_type, is_deleted=False)
            .order_by(ZCCResource.name)
            .all()
        )
        return [row.raw_config for row in rows if row.raw_config]


def _normalize_name(record: Dict, *candidate_keys: str) -> Dict:
    """Add a 'name' key from the first non-empty candidate field, if not already present."""
    if record.get("name"):
        return record
    for key in candidate_keys:
        val = record.get(key)
        if val:
            return {**record, "name": val}
    return record


@router.get("/{tenant}/trusted-networks")
def list_trusted_networks(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "trusted_network")
    return [_normalize_name(r, "network_name") for r in rows]


@router.get("/{tenant}/forwarding-profiles")
def list_forwarding_profiles(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "forwarding_profile")


@router.get("/{tenant}/web-policies")
def list_web_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "web_policy")


@router.get("/{tenant}/web-app-services")
def list_web_app_services(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "web_app_service")
    return [_normalize_name(r, "app_name") for r in rows]


@router.get("/{tenant}/admin-roles")
def list_admin_roles(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "admin_role")
    return [_normalize_name(r, "role_name") for r in rows]


@router.get("/{tenant}/fail-open-policies")
def list_fail_open_policies(tenant: str, user: AuthUser = Depends(require_auth)):
    return _db_resources(tenant, user, "fail_open_policy")


@router.get("/{tenant}/web-privacy")
def get_web_privacy(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "web_privacy")
    return rows[0] if rows else {}


@router.get("/{tenant}/ip-apps/predefined")
def list_ip_apps_predefined(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "ip_app_predefined")
    return [_normalize_name(r, "appName") for r in rows]


@router.get("/{tenant}/ip-apps/custom")
def list_ip_apps_custom(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "ip_app_custom")
    return [_normalize_name(r, "appName") for r in rows]


@router.get("/{tenant}/process-apps")
def list_process_apps(tenant: str, user: AuthUser = Depends(require_auth)):
    rows = _db_resources(tenant, user, "process_app")
    return [_normalize_name(r, "appName") for r in rows]


# ------------------------------------------------------------------
# Traffic Profile
# ------------------------------------------------------------------

@router.get("/{tenant}/traffic-profile/{policy_id}")
def get_traffic_profile(
    tenant: str,
    policy_id: str,
    user: AuthUser = Depends(require_auth),
):
    from db.database import get_session
    from db.models import ZCCResource, ZIAResource
    from api.dependencies import check_tenant_access
    from services.config_service import get_tenant as _get_tenant

    t = _get_tenant(tenant)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant}' not found")
    check_tenant_access(t.id, user)

    with get_session() as session:
        # Policy IDs from _to_camel_dict may be stored as floats ("217591.0") because
        # JSON numbers without a fractional part still become Python floats via the SDK.
        # The frontend coerces them to integers, so try both forms.
        policy_id_candidates = [policy_id]
        if not policy_id.endswith(".0"):
            policy_id_candidates.append(policy_id + ".0")
        policy_row = (
            session.query(ZCCResource)
            .filter(
                ZCCResource.tenant_id == t.id,
                ZCCResource.resource_type == "web_policy",
                ZCCResource.zcc_id.in_(policy_id_candidates),
                ZCCResource.is_deleted == False,  # noqa: E712
            )
            .first()
        )
        if not policy_row:
            raise HTTPException(status_code=404, detail="App profile not found")

        raw_policy = policy_row.raw_config or {}
        # onNetPolicy is the forwarding profile embedded inline by the direct HTTP
        # import (list_web_policies via _direct_get). Use it directly when present.
        raw_fp = raw_policy.get("onNetPolicy") or None
        if not raw_fp:
            # Legacy fallback: look up forwarding_profile by ID for records imported
            # before the switch to _direct_get (which embeds onNetPolicy).
            fp_id = str(raw_policy.get("forwardingProfileId", ""))
            if fp_id:
                fp_id_candidates = [fp_id]
                if fp_id.endswith(".0"):
                    fp_id_candidates.append(fp_id[:-2])
                else:
                    fp_id_candidates.append(fp_id + ".0")
                fp_row = (
                    session.query(ZCCResource)
                    .filter(
                        ZCCResource.tenant_id == t.id,
                        ZCCResource.resource_type == "forwarding_profile",
                        ZCCResource.zcc_id.in_(fp_id_candidates),
                        ZCCResource.is_deleted == False,  # noqa: E712
                    )
                    .first()
                )
                if fp_row:
                    raw_fp = fp_row.raw_config

        # Cross-reference PAC URL against ZIA pac_file resources
        pac_url = raw_policy.get("pac_url") or raw_policy.get("pacUrl") or ""
        zia_pac_file_id = None
        zia_pac_file_name = None
        if pac_url:
            zia_pac_rows = (
                session.query(ZIAResource)
                .filter_by(tenant_id=t.id, resource_type="pac_file", is_deleted=False)
                .all()
            )
            for pac_row in zia_pac_rows:
                rc = pac_row.raw_config or {}
                row_url = rc.get("pac_url") or rc.get("pacUrl") or rc.get("url") or ""
                if row_url and row_url == pac_url:
                    zia_pac_file_id = pac_row.zia_id
                    zia_pac_file_name = pac_row.name
                    break

        # Resolve bypassAppIds → ip_app_predefined DB records
        bypass_app_ids = {str(i) for i in (raw_policy.get("bypassAppIds") or [])}
        bypass_custom_ids = {str(i) for i in (raw_policy.get("bypassCustomAppIds") or [])}
        app_service_ids = {str(i) for i in (raw_policy.get("appServiceIds") or [])}

        def _resolve_ip_apps(resource_type: str, id_set: set, source: str) -> List[Dict]:
            if not id_set:
                return []
            rows = (
                session.query(ZCCResource)
                .filter(
                    ZCCResource.tenant_id == t.id,
                    ZCCResource.resource_type == resource_type,
                    ZCCResource.is_deleted == False,  # noqa: E712
                    ZCCResource.zcc_id.in_(id_set),
                )
                .all()
            )
            result = []
            for row in rows:
                rc = row.raw_config or {}
                blob = rc.get("appDataBlob") or []
                blob_v6 = rc.get("appDataBlobV6") or []
                result.append({
                    "id": row.zcc_id,
                    "appName": rc.get("appName") or row.name or row.zcc_id,
                    "cidrs": blob if isinstance(blob, list) else [blob],
                    "cidrsV6": blob_v6 if isinstance(blob_v6, list) else [blob_v6],
                    "source": source,
                })
            return result

        predefined_ip_bypasses = _resolve_ip_apps("ip_app_predefined", bypass_app_ids, "predefined")
        custom_ip_bypasses = _resolve_ip_apps("ip_app_custom", bypass_custom_ids, "custom")

        app_service_bypasses: List[Dict] = []
        if app_service_ids:
            svc_rows = (
                session.query(ZCCResource)
                .filter(
                    ZCCResource.tenant_id == t.id,
                    ZCCResource.resource_type == "web_app_service",
                    ZCCResource.is_deleted == False,  # noqa: E712
                    ZCCResource.zcc_id.in_(app_service_ids),
                )
                .all()
            )
            for row in svc_rows:
                rc = row.raw_config or {}
                proc_names = rc.get("process_names") or rc.get("processNames") or rc.get("app_process_names") or []
                app_service_bypasses.append({
                    "id": row.zcc_id,
                    "appName": rc.get("appName") or row.name or row.zcc_id,
                    "processNames": proc_names if isinstance(proc_names, list) else [proc_names],
                })

    return _build_traffic_profile(
        raw_policy, raw_fp, zia_pac_file_id, zia_pac_file_name,
        predefined_ip_bypasses, custom_ip_bypasses, app_service_bypasses,
    )


# ------------------------------------------------------------------
# Snapshots
# ------------------------------------------------------------------

@router.post("/{tenant}/snapshots")
def create_snapshot(
    tenant: str,
    body: SnapshotCreateRequest,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_snapshot_service(tenant, user)
    snap = svc.create_snapshot(body.label, body.note)
    return {
        "id": snap.id,
        "label": snap.label,
        "note": snap.note,
        "created_at": snap.created_at.isoformat(),
        "resource_count": snap.resource_count,
    }


@router.get("/{tenant}/snapshots")
def list_snapshots(
    tenant: str,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_snapshot_service(tenant, user)
    snaps = svc.list_snapshots()
    return [
        {
            "id": s.id,
            "label": s.label,
            "note": s.note,
            "created_at": s.created_at.isoformat(),
            "resource_count": s.resource_count,
        }
        for s in snaps
    ]


@router.delete("/{tenant}/snapshots/{snapshot_id}")
def delete_snapshot(
    tenant: str,
    snapshot_id: int,
    user: AuthUser = Depends(require_admin),
):
    svc = _get_snapshot_service(tenant, user)
    try:
        svc.delete_snapshot(snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.get("/{tenant}/snapshots/{snapshot_id}/diff")
def diff_snapshot(
    tenant: str,
    snapshot_id: int,
    user: AuthUser = Depends(require_auth),
):
    svc = _get_snapshot_service(tenant, user)
    try:
        return svc.diff_snapshot(snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{tenant}/snapshots/{snapshot_id}/restore")
def restore_snapshot(
    tenant: str,
    snapshot_id: int,
    body: SnapshotRestoreRequest,
    user: AuthUser = Depends(require_admin),
):
    from lib.auth import ZscalerAuth
    from lib.zcc_client import ZCCClient
    from services.config_service import decrypt_secret, get_tenant as _get_tenant
    from services.zcc_snapshot_service import ZCCSnapshotService

    svc = _get_snapshot_service(tenant, user)

    target_client = None
    target_tenant_id = None
    if body.target_tenant:
        tgt = _get_tenant(body.target_tenant)
        if not tgt:
            raise HTTPException(status_code=404, detail=f"Target tenant '{body.target_tenant}' not found")
        tgt_auth = ZscalerAuth(
            tgt.zidentity_base_url,
            tgt.client_id,
            decrypt_secret(tgt.client_secret_enc),
            govcloud=bool(tgt.govcloud),
        )
        target_client = ZCCClient(tgt_auth, tgt.oneapi_base_url, tgt.zia_cloud, tgt.zia_tenant_id)
        target_tenant_id = tgt.id

    try:
        result = svc.restore_snapshot(
            snapshot_id=snapshot_id,
            resource_types=body.resource_types,
            dry_run=body.dry_run,
            target_client=target_client,
            target_tenant_id=target_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result
