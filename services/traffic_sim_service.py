"""Traffic simulation service.

Evaluates a destination + port + protocol against imported ZIA and ZPA policy
data and returns a step-by-step verdict.  All evaluation is done offline against
the local DB snapshot; no live API calls are made.

Limitations (inherent to offline evaluation):
  - ZIA URL filtering predefined categories (e.g. SOCIAL_NETWORKING) require
    a live category-lookup call; we mark those as "cannot determine offline".
  - Firewall / DNS rules scoped to specific users, departments, or groups are
    evaluated as if the scope constraint is met (worst-case / most-permissive
    read).  Pass user context in the future to be more precise.
  - Rule order is respected; the first matching ENABLED rule wins.
  - ZCC PAC DIRECT rules are evaluated against the PAC script captured at import
    time (pac_file.pacContent). If the content isn't cached, we fall back to a
    live fetch of the PAC URL (treated as trusted, like the ZIA url_lookup below).
"""

import fnmatch
import ipaddress
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import ast

from db.database import get_session
from db.models import ZCCResource, ZIAResource, ZPAResource


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PolicyCheck:
    engine: str                     # "ZIA Firewall", "ZIA DNS", "ZIA URL Filter", "ZPA"
    matched: bool = False
    rule_name: Optional[str] = None
    action: Optional[str] = None    # ALLOW, BLOCK, BLOCK_DROP, REDIRECT, etc.
    reason: str = ""
    category: Optional[str] = None  # URL category for URL filter checks
    caveats: List[str] = field(default_factory=list)


@dataclass
class SimulationResult:
    destination: str
    port: int
    protocol: str
    zcc_bypass: PolicyCheck
    zpa: PolicyCheck
    zia_firewall: PolicyCheck
    zia_dns: PolicyCheck
    zia_url: PolicyCheck
    zia_ssl: PolicyCheck
    zia_cloud_app: PolicyCheck
    zia_exceptions: PolicyCheck
    verdict: str          # precedence: ZCC_BYPASS > ZPA > ZIA_BLOCK_DNS > ZIA_BLOCK_FIREWALL > ZIA_BLOCK_CLOUDAPP > ZIA_BLOCK_URL > ZIA_ALLOW (also ZCC_INACTIVE)
    verdict_label: str    # human-readable


# ---------------------------------------------------------------------------
# IP / hostname helpers
# ---------------------------------------------------------------------------

def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _ip_in_cidr(ip_str: str, network_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str) in ipaddress.ip_network(network_str, strict=False)
    except ValueError:
        return False


def _ip_matches_any(ip_str: str, addresses: List[str]) -> bool:
    """True if ip_str matches any address (exact or CIDR) in the list."""
    for addr in addresses:
        addr = addr.strip()
        if not addr:
            continue
        try:
            if "/" in addr:
                if _ip_in_cidr(ip_str, addr):
                    return True
            else:
                if ipaddress.ip_address(ip_str) == ipaddress.ip_address(addr):
                    return True
        except ValueError:
            pass
    return False


def _hostname_matches(dest: str, pattern: str) -> bool:
    """Match dest against pattern with wildcard support (*, ?)."""
    dest = dest.lower().lstrip("https://").lstrip("http://").split("/")[0]
    pattern = pattern.lower().lstrip("*.")
    return dest == pattern or dest.endswith("." + pattern) or fnmatch.fnmatch(dest, pattern)


def _port_in_ranges(port: int, ranges: List[Dict]) -> bool:
    """ranges is a list of {from, to} dicts (ZPA format)."""
    for r in ranges:
        try:
            if int(r.get("from", 0)) <= port <= int(r.get("to", 65535)):
                return True
        except (TypeError, ValueError):
            pass
    return False


def _port_in_list(port: int, port_list: List[Dict]) -> bool:
    """port_list is a list of {start, end} dicts (ZIA network service format).
    ZIA stores single-port ranges as {start: N, end: None} so we must treat None end as == start.
    """
    for r in port_list:
        try:
            start_val = r.get("start") if r.get("start") is not None else r.get("s")
            end_val = r.get("end") if r.get("end") is not None else r.get("e")
            start = int(start_val or 0)
            end = int(end_val) if end_val is not None else start
            if start <= port <= end:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _strip_url(dest: str) -> str:
    """Return just the hostname from a URL or bare hostname."""
    dest = dest.strip()
    if "://" in dest:
        dest = dest.split("://", 1)[1]
    return dest.split("/")[0].split(":")[0].lower()


# ---------------------------------------------------------------------------
# ZPA evaluation
# ---------------------------------------------------------------------------

def _eval_zpa(tenant_id: int, dest: str, port: int, protocol: str) -> PolicyCheck:
    check = PolicyCheck(engine="ZPA")
    hostname = _strip_url(dest)

    with get_session() as s:
        apps = (
            s.query(ZPAResource)
            .filter_by(tenant_id=tenant_id, resource_type="application", is_deleted=False)
            .all()
        )

    def _domain_specificity(app) -> int:
        """Higher = more specific. Exact hostname > wildcard > IP."""
        cfg = app.raw_config or {}
        domains = cfg.get("domainNames", cfg.get("domain_names", []))
        if hostname in domains or dest in domains:
            return 2  # exact match
        if any(d.startswith("*.") for d in domains):
            return 0  # wildcard
        return 1

    # Sort most-specific first so exact hostname beats wildcard
    sorted_apps = sorted(
        [a for a in apps if (a.raw_config or {}).get("enabled", True)],
        key=_domain_specificity,
        reverse=True,
    )

    matched_app = None
    for app in sorted_apps:
        cfg = app.raw_config or {}
        domain_names: List[str] = cfg.get("domainNames", cfg.get("domain_names", []))
        tcp_ranges: List[Dict] = cfg.get("tcpPortRange", cfg.get("tcp_port_range", []))
        udp_ranges: List[Dict] = cfg.get("udpPortRange", cfg.get("udp_port_range", []))

        # Destination match
        dest_match = False
        if _is_ip(dest):
            dest_match = dest in domain_names
        else:
            dest_match = any(_hostname_matches(hostname, d) for d in domain_names)

        if not dest_match:
            continue

        # Port match
        use_udp = protocol.upper() in ("UDP", "DNS")
        ranges = udp_ranges if use_udp else tcp_ranges
        if ranges and not _port_in_ranges(port, ranges):
            continue

        matched_app = app
        break

    if matched_app:
        cfg = matched_app.raw_config or {}
        seg_id = str(cfg.get("id", ""))
        check.matched = True
        check.rule_name = cfg.get("name", "Unknown App Segment")
        check.action = "ALLOW"
        check.reason = f'Destination matches ZPA application segment "{check.rule_name}"'

        # Find access policies that reference this segment and extract requirements
        with get_session() as s:
            access_policies = s.query(ZPAResource).filter_by(
                tenant_id=tenant_id, resource_type="policy_access", is_deleted=False
            ).all()
            scim_groups = s.query(ZPAResource).filter_by(
                tenant_id=tenant_id, resource_type="scim_group", is_deleted=False
            ).all()
            saml_attrs = s.query(ZPAResource).filter_by(
                tenant_id=tenant_id, resource_type="saml_attribute", is_deleted=False
            ).all()

        scim_group_map = {str((r.raw_config or {}).get("id", "")): (r.raw_config or {}).get("name", "") for r in scim_groups}
        saml_attr_map = {str((r.raw_config or {}).get("id", "")): (r.raw_config or {}).get("name", "") for r in saml_attrs}

        _OBJ_LABEL = {
            "APP": "App", "APP_GROUP": "Segment Group",
            "SAML": "Identity", "SCIM": "SCIM User", "SCIM_GROUP": "SCIM Group",
            "CLIENT_TYPE": "Client Type", "POSTURE": "Device Posture",
            "PLATFORM": "Platform", "TRUSTED_NETWORK": "Trusted Network",
            "IDP": "IdP", "COUNTRY_CODE": "Country",
        }

        policy_summaries = []
        for pol in access_policies:
            pcfg = pol.raw_config or {}
            if pcfg.get("disabled") == "1" or pcfg.get("action") == "DENY":
                continue
            conditions = pcfg.get("conditions", [])
            # Check if this policy references our segment
            refs_segment = any(
                op.get("object_type") == "APP" and op.get("rhs") == seg_id
                for cond in conditions for op in cond.get("operands", [])
            )
            if not refs_segment:
                continue
            # Extract non-APP conditions as access requirements
            reqs = []
            for cond in conditions:
                for op in cond.get("operands", []):
                    ot = op.get("object_type", "")
                    if ot == "APP":
                        continue
                    label = _OBJ_LABEL.get(ot, ot)
                    rhs = str(op.get("rhs", ""))
                    if ot == "SCIM_GROUP":
                        name = scim_group_map.get(rhs) or op.get("name") or rhs
                    elif ot == "SAML":
                        attr_id = str(op.get("lhs", ""))
                        attr_name = saml_attr_map.get(attr_id) or op.get("name") or attr_id
                        name = f"{attr_name}={rhs}"
                    else:
                        name = op.get("name") or rhs
                    if name:
                        reqs.append(f"{label}: {name}")
            summary = f'Policy "{pcfg.get("name", "?")}": '
            summary += (", ".join(reqs) if reqs else "No user/group restrictions")
            policy_summaries.append(summary)

        if policy_summaries:
            check.caveats = [f"ZPA access requirements — {s}" for s in policy_summaries]
        else:
            check.caveats = ["No ZPA access policies found for this segment — access may be unrestricted"]
    else:
        check.reason = "No ZPA application segment matches this destination / port"

    return check


# ---------------------------------------------------------------------------
# ZIA Firewall evaluation
# ---------------------------------------------------------------------------

def _resolve_ip_dest_groups(tenant_id: int, s) -> Dict[int, List[str]]:
    """Return {group_id: [address, ...]} for all IP destination groups."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="ip_destination_group", is_deleted=False).all()
    result: Dict[int, List[str]] = {}
    for row in rows:
        cfg = row.raw_config or {}
        gid = cfg.get("id")
        if gid is not None:
            addresses = cfg.get("addresses", [])
            ip_ranges = cfg.get("ipRanges", cfg.get("ip_ranges", []))
            result[int(gid)] = list(addresses) + list(ip_ranges)
    return result


def _resolve_network_services(tenant_id: int, s) -> Dict[int, Dict]:
    """Return {svc_id: raw_config} for all network services."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="network_service", is_deleted=False).all()
    result: Dict[int, Dict] = {}
    for row in rows:
        cfg = row.raw_config or {}
        sid = cfg.get("id")
        if sid is not None:
            result[int(sid)] = cfg
    return result


def _resolve_network_service_groups(tenant_id: int, s) -> Dict[int, List[int]]:
    """Return {group_id: [service_id, ...]} for all network service groups."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="network_svc_group", is_deleted=False).all()
    result: Dict[int, List[int]] = {}
    for row in rows:
        cfg = row.raw_config or {}
        gid = cfg.get("id")
        if gid is not None:
            svc_ids = [int(svc["id"]) for svc in cfg.get("services", []) if svc.get("id") is not None]
            result[int(gid)] = svc_ids
    return result


def _resolve_src_ip_groups(tenant_id: int, s) -> Dict[int, List[str]]:
    """Return {group_id: [address, ...]} for all IP source groups."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="ip_source_group", is_deleted=False).all()
    result: Dict[int, List[str]] = {}
    for row in rows:
        cfg = row.raw_config or {}
        gid = cfg.get("id")
        if gid is not None:
            addresses = cfg.get("ip_addresses", cfg.get("ipAddresses", []))
            result[int(gid)] = list(addresses)
    return result


def _resolve_nw_application_groups(tenant_id: int, s) -> Dict[int, List[str]]:
    """Return {group_id: [app_name, ...]} for all network application groups."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="nw_application_group", is_deleted=False).all()
    result: Dict[int, List[str]] = {}
    for row in rows:
        cfg = row.raw_config or {}
        gid = cfg.get("id")
        if gid is not None:
            apps = [str(a) for a in cfg.get("nw_applications", []) if a]
            result[int(gid)] = apps
    return result


def _name_in_list(name: str, ref_list: List[Dict]) -> bool:
    """True if name matches any {id, name} ref in a list (case-insensitive)."""
    name_upper = name.upper()
    return any(
        (ref.get("name") or "").upper() == name_upper
        for ref in ref_list
        if isinstance(ref, dict)
    )


def _svc_matches_port(svc_cfg: Dict, port: int, protocol: str) -> bool:
    """True if a network service config matches the given port + protocol."""
    proto = protocol.upper()
    use_udp = proto in ("UDP", "DNS")
    use_tcp = proto in ("TCP", "HTTP", "HTTPS", "FTP", "SMTP", "POP3", "IMAP", "SSH", "TELNET", "LDAP", "LDAPS")

    tcp_dest = svc_cfg.get("dest_tcp_ports", [])
    udp_dest = svc_cfg.get("dest_udp_ports", [])
    # Some services match all traffic (ICMP, ANY)
    tag = (svc_cfg.get("tag") or "").upper()
    if "ICMP" in tag or "ANY" in tag:
        return True

    if use_udp and udp_dest:
        return _port_in_list(port, udp_dest)
    if use_tcp and tcp_dest:
        return _port_in_list(port, tcp_dest)
    # No port constraints → service matches all (e.g. protocol-based service)
    if not tcp_dest and not udp_dest:
        return True
    return False


def _fw_rule_matches(
    cfg: Dict, dest: str, port: int, protocol: str,
    ip_dest_groups: Dict[int, List[str]],
    nw_services: Dict[int, Dict],
    nw_svc_groups: Dict[int, List[int]] = None,
    nw_application: Optional[str] = None,
    app_service_group: Optional[str] = None,
    src_ip: Optional[str] = None,
    ip_src_groups: Dict[int, List[str]] = None,
    nw_app_groups: Dict[int, List[str]] = None,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
) -> bool:
    """Evaluate one firewall rule. Returns True if ALL constraints match (AND semantics).
    Empty constraint list = wildcard. Constraints that can't be evaluated offline are
    skipped (treated as matching) unless explicit input is provided.
    """
    if cfg.get("state", "ENABLED") != "ENABLED":
        return False

    dest_is_ip = _is_ip(dest)

    # ── Destination IP / category check ──────────────────────────────────
    dest_addrs: List[str] = cfg.get("dest_addresses", [])
    dest_ip_grp_refs: List[Dict] = cfg.get("dest_ip_groups", [])
    dest_ip_cats: List[str] = cfg.get("dest_ip_categories", [])
    dest_countries: List[str] = cfg.get("dest_countries", [])

    has_resolvable_dest = bool(dest_addrs or dest_ip_grp_refs)
    has_unresolvable_dest = bool(dest_ip_cats or dest_countries)

    if has_resolvable_dest:
        dest_matched = False
        if dest_addrs and dest_is_ip:
            dest_matched = _ip_matches_any(dest, dest_addrs)
        if not dest_matched and dest_ip_grp_refs and dest_is_ip:
            for grp in dest_ip_grp_refs:
                gid = grp.get("id")
                if gid and int(gid) in ip_dest_groups:
                    if _ip_matches_any(dest, ip_dest_groups[int(gid)]):
                        dest_matched = True
                        break
        if not dest_matched:
            return False
    elif has_unresolvable_dest:
        # Predefined IP category or country-based — can't resolve offline
        return False

    # ── Source IP check ───────────────────────────────────────────────────
    src_ip_grp_refs: List[Dict] = cfg.get("src_ip_groups", [])
    if src_ip_grp_refs and src_ip and ip_src_groups is not None:
        src_matched = False
        for grp in src_ip_grp_refs:
            gid = grp.get("id")
            if gid and int(gid) in ip_src_groups:
                if _ip_matches_any(src_ip, ip_src_groups[int(gid)]):
                    src_matched = True
                    break
        if not src_matched:
            return False
    # If src_ip_groups present but no src_ip provided → assume match (permissive)

    # ── Application-layer constraint ──────────────────────────────────────
    rule_nw_apps: List[str] = cfg.get("nw_applications", [])
    rule_nw_app_grps: List[Dict] = cfg.get("nw_application_groups", [])
    rule_app_svc_grps: List[Dict] = cfg.get("app_service_groups", [])
    has_port_svc = bool(cfg.get("nw_services") or cfg.get("nw_service_groups"))
    has_app_constraint = bool(rule_nw_apps or rule_nw_app_grps or rule_app_svc_grps)

    if has_app_constraint and not has_port_svc:
        # Expand nw_application_groups → individual app names
        expanded_apps = list(rule_nw_apps)
        if nw_app_groups is not None:
            for grp_ref in rule_nw_app_grps:
                gid = grp_ref.get("id")
                if gid is not None:
                    expanded_apps.extend(nw_app_groups.get(int(gid), []))

        if nw_application and expanded_apps:
            if nw_application.upper() in [a.upper() for a in expanded_apps]:
                return True
        if app_service_group and rule_app_svc_grps:
            grp_names = [
                (g.get("name") or "").upper() if isinstance(g, dict) else str(g).upper()
                for g in rule_app_svc_grps
            ]
            if app_service_group.upper() in grp_names:
                return True
        return False

    # ── Port / service check ──────────────────────────────────────────────
    rule_services: List[Dict] = cfg.get("nw_services", [])
    rule_svc_groups: List[Dict] = cfg.get("nw_service_groups", [])
    has_svc_constraint = bool(rule_services or rule_svc_groups)

    if has_svc_constraint:
        svc_matched = False
        for svc_ref in rule_services:
            svc_id = svc_ref.get("id")
            embedded_tcp = svc_ref.get("dest_tcp_ports", [])
            embedded_udp = svc_ref.get("dest_udp_ports", [])
            if embedded_tcp or embedded_udp:
                svc_cfg = svc_ref
            elif svc_id and int(svc_id) in nw_services:
                svc_cfg = nw_services[int(svc_id)]
            else:
                svc_cfg = svc_ref
            if _svc_matches_port(svc_cfg, port, protocol):
                svc_matched = True
                break
        if not svc_matched and rule_svc_groups and nw_svc_groups is not None:
            for grp_ref in rule_svc_groups:
                gid = grp_ref.get("id")
                if gid is None:
                    continue
                for svc_id in nw_svc_groups.get(int(gid), []):
                    if svc_id in nw_services:
                        if _svc_matches_port(nw_services[svc_id], port, protocol):
                            svc_matched = True
                            break
                if svc_matched:
                    break
        if not svc_matched:
            return False

    # ── Identity / location constraints (scoped rules) ────────────────────
    rule_users: List[Dict] = cfg.get("users", [])
    rule_depts: List[Dict] = cfg.get("departments", [])
    rule_groups: List[Dict] = cfg.get("groups", [])
    rule_locs: List[Dict] = cfg.get("locations", [])

    if rule_users and user_name:
        if not _name_in_list(user_name, rule_users):
            return False
    if rule_depts and dept_name:
        if not _name_in_list(dept_name, rule_depts):
            return False
    if rule_groups and group_name:
        if not _name_in_list(group_name, rule_groups):
            return False
    if rule_locs and location_name:
        if not _name_in_list(location_name, rule_locs):
            return False
    # If scoped but no input provided → assume match (permissive)

    return True


def _eval_zia_firewall(
    tenant_id: int, dest: str, port: int, protocol: str,
    nw_application: Optional[str] = None,
    app_service_group: Optional[str] = None,
    src_ip: Optional[str] = None,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA Firewall")

    with get_session() as s:
        rules = (
            s.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False)
            .all()
        )
        ip_dest_groups = _resolve_ip_dest_groups(tenant_id, s)
        ip_src_groups = _resolve_src_ip_groups(tenant_id, s)
        nw_services = _resolve_network_services(tenant_id, s)
        nw_svc_groups = _resolve_network_service_groups(tenant_id, s)
        nw_app_groups = _resolve_nw_application_groups(tenant_id, s)

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    non_default = [r for r in enabled if not (r.raw_config or {}).get("default_rule")]
    default_rules = [r for r in enabled if (r.raw_config or {}).get("default_rule")]
    non_default.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))
    ordered = non_default + default_rules

    for rule in ordered:
        cfg = rule.raw_config or {}
        if cfg.get("default_rule"):
            check.matched = True
            check.rule_name = cfg.get("name", "Default Firewall Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched default firewall rule "{check.rule_name}" (catch-all)'
            break
        if _fw_rule_matches(
            cfg, dest, port, protocol,
            ip_dest_groups, nw_services, nw_svc_groups,
            nw_application, app_service_group,
            src_ip, ip_src_groups, nw_app_groups,
            user_name, dept_name, group_name, location_name,
        ):
            check.matched = True
            check.rule_name = cfg.get("name", "Unknown Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched firewall rule "{check.rule_name}" (order {cfg.get("order", "?")})'
            break

    if not check.matched:
        check.reason = "No firewall rule matched — traffic will hit the default rule"

    # ── Caveats ──────────────────────────────────────────────────────────
    app_only_rules = [
        (r.raw_config or {}).get("name", "?")
        for r in non_default
        if ((r.raw_config or {}).get("nw_applications") or (r.raw_config or {}).get("app_service_groups")
            or (r.raw_config or {}).get("nw_application_groups"))
        and not (r.raw_config or {}).get("nw_services")
        and not (r.raw_config or {}).get("nw_service_groups")
    ]
    if app_only_rules and not nw_application and not app_service_group:
        check.caveats.append(
            "Rules using application-layer matching were skipped (specify Network Application or App Service Group to evaluate): "
            + ", ".join(f'"{n}"' for n in app_only_rules[:5])
            + (f" +{len(app_only_rules)-5} more" if len(app_only_rules) > 5 else "")
        )

    ip_cat_rules = [
        (r.raw_config or {}).get("name", "?")
        for r in non_default
        if (r.raw_config or {}).get("dest_ip_categories") or (r.raw_config or {}).get("dest_countries")
        and not (r.raw_config or {}).get("dest_addresses")
        and not (r.raw_config or {}).get("dest_ip_groups")
    ]
    if ip_cat_rules:
        check.caveats.append(
            "Rules using predefined IP categories or country constraints cannot be evaluated offline and were skipped: "
            + ", ".join(f'"{n}"' for n in ip_cat_rules[:5])
            + (f" +{len(ip_cat_rules)-5} more" if len(ip_cat_rules) > 5 else "")
        )

    scoped_rules = [
        (r.raw_config or {}).get("name", "?")
        for r in non_default
        if any((r.raw_config or {}).get(f) for f in ("users", "departments", "groups", "locations"))
    ]
    if scoped_rules and not any([user_name, dept_name, group_name, location_name]):
        check.caveats.append(
            "Rules scoped to users/departments/groups/locations were evaluated permissively (specify identity context for precise results): "
            + ", ".join(f'"{n}"' for n in scoped_rules[:5])
            + (f" +{len(scoped_rules)-5} more" if len(scoped_rules) > 5 else "")
        )

    if not _is_ip(dest):
        check.caveats.append(
            "Destination is a hostname; firewall IP matching may not apply if ZIA resolves DNS differently"
        )

    return check


# ---------------------------------------------------------------------------
# ZIA DNS Filtering evaluation
# ---------------------------------------------------------------------------

def _zia_url_lookup(tenant_id: int, dest: str) -> Optional[List[str]]:
    """Call ZIA urlLookup for dest and return list of category strings, or None on failure."""
    try:
        from db.models import TenantConfig
        from lib.auth import ZscalerAuth
        from lib.zia_client import ZIAClient
        from services.config_service import decrypt_secret
        with get_session() as s:
            t = s.get(TenantConfig, tenant_id)
            if not t:
                return None
            auth = ZscalerAuth(
                t.zidentity_base_url, t.client_id,
                decrypt_secret(t.client_secret_enc),
                govcloud=bool(t.govcloud),
            )
            client = ZIAClient(auth, t.oneapi_base_url)
            results = client.url_lookup([dest])
            if not results:
                return []
            cats: List[str] = []
            for item in results:
                cats.extend(item.get("urlClassifications", []))
                cats.extend(item.get("urlClassificationsWithSecurityAlert", []))
            return cats
    except Exception:
        return None


def _eval_zia_dns(tenant_id: int, dest: str, port: int, protocol: str, live_cats: Optional[List[str]] = None) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA DNS Filter")

    with get_session() as s:
        rules = (
            s.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="firewall_dns_rule", is_deleted=False)
            .all()
        )
        ip_groups = _resolve_ip_dest_groups(tenant_id, s)

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    non_default_dns = [r for r in enabled if not (r.raw_config or {}).get("default_rule")]
    default_dns = [r for r in enabled if (r.raw_config or {}).get("default_rule")]
    non_default_dns.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))
    ordered_dns = non_default_dns + default_dns

    for rule in ordered_dns:
        cfg = rule.raw_config or {}
        if cfg.get("default_rule"):
            check.matched = True
            check.rule_name = cfg.get("name", "Default DNS Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched default DNS rule "{check.rule_name}" (catch-all)'
            break

        dest_addrs: List[str] = cfg.get("dest_addresses", [])
        dest_ip_groups_ref: List[Dict] = cfg.get("dest_ip_groups", [])
        dest_ip_cats: List[str] = cfg.get("dest_ip_categories", [])
        res_cats: List[str] = cfg.get("res_categories", [])
        applications: List[str] = cfg.get("applications", [])
        has_dest = bool(dest_addrs or dest_ip_groups_ref or dest_ip_cats or res_cats or applications)

        if has_dest:
            if dest_ip_cats or res_cats or applications:
                skip_reason_parts = []
                # In DNS rules, dest_ip_categories and res_categories are domain/URL
                # categories that url_lookup can resolve. Evaluate both with live_cats.
                all_url_cats = list(set(dest_ip_cats + res_cats))
                if all_url_cats:
                    if live_cats is not None:
                        matched_cats = [c for c in all_url_cats if c in live_cats]
                        if matched_cats:
                            # Live lookup matched — rule applies, fall through to dest check
                            pass
                        else:
                            # Live lookup returned but no match — rule does not apply
                            if not applications:
                                continue
                            # applications still need to be skipped with caveat
                    else:
                        skip_reason_parts.append(
                            f'categories ({", ".join(all_url_cats[:5])}{"..." if len(all_url_cats) > 5 else ""})'
                        )

                # applications require traffic inspection — always skip
                if applications:
                    skip_reason_parts.append(f'applications ({", ".join(applications[:5])}{"..." if len(applications) > 5 else ""})')

                if skip_reason_parts:
                    check.caveats.append(
                        f'Rule "{cfg.get("name")}" skipped offline — uses {" and ".join(skip_reason_parts)} that require a live ZIA lookup'
                    )
                    if applications and not (live_cats is not None and matched_cats):
                        continue

            # Category match via live lookup counts as destination match
            cat_matched = bool(
                (dest_ip_cats or res_cats) and live_cats is not None
                and any(c in live_cats for c in set(dest_ip_cats + res_cats))
            )
            dest_matched = cat_matched
            if not dest_matched:
                if _is_ip(dest):
                    if dest_addrs:
                        dest_matched = _ip_matches_any(dest, dest_addrs)
                    if not dest_matched:
                        for grp in dest_ip_groups_ref:
                            gid = grp.get("id")
                            if gid and int(gid) in ip_groups:
                                if _ip_matches_any(dest, ip_groups[int(gid)]):
                                    dest_matched = True
                                    break
            if not dest_matched:
                continue

        check.matched = True
        check.rule_name = cfg.get("name", "Unknown DNS Rule")
        check.action = cfg.get("action", "ALLOW")
        check.reason = f'Matched DNS rule "{check.rule_name}" (order {cfg.get("order", "?")})'
        break

    if not check.matched:
        check.reason = "No DNS filter rule matched — traffic uses default DNS policy"

    return check


# ---------------------------------------------------------------------------
# ZIA URL Filtering evaluation
# ---------------------------------------------------------------------------

def _resolve_url_categories(tenant_id: int, s) -> Dict[str, Dict]:
    """Return {category_id: raw_config} for all URL categories."""
    rows = s.query(ZIAResource).filter_by(tenant_id=tenant_id, resource_type="url_category", is_deleted=False).all()
    result: Dict[str, Dict] = {}
    for row in rows:
        cfg = row.raw_config or {}
        cid = cfg.get("id") or cfg.get("configured_name")
        if cid:
            result[str(cid)] = cfg
    return result


def _url_in_category(hostname: str, cat_cfg: Dict) -> bool:
    """True if hostname is listed in a URL category (custom or predefined)."""
    for url_list in (cat_cfg.get("custom_urls", []), cat_cfg.get("urls", []), cat_cfg.get("db_categorized_urls", [])):
        for raw_url in url_list:
            url = _strip_url(raw_url) if raw_url else ""
            if not url:
                continue
            if hostname == url or hostname.endswith("." + url) or fnmatch.fnmatch(hostname, url):
                return True
    return False


def _eval_zia_url(
    tenant_id: int, dest: str, port: int, protocol: str,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
    live_cats: Optional[List[str]] = None,
) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA URL Filter")

    if _is_ip(dest):
        check.reason = "URL filtering applies to hostnames only; destination is an IP address"
        check.caveats.append("IP-based URL categories not evaluated")
        return check

    hostname = _strip_url(dest)
    proto_upper = protocol.upper()

    with get_session() as s:
        rules = (
            s.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="url_filtering_rule", is_deleted=False)
            .all()
        )
        categories = _resolve_url_categories(tenant_id, s)

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    enabled.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))

    predefined_rules: List[str] = []   # rules skipped because they use predefined categories (no live lookup)
    scoped_rules: List[str] = []       # rules carrying user/dept/group/location scope
    has_identity = any([user_name, dept_name, group_name, location_name])
    # Live-resolved URL classifications (from ZIA url_lookup) let us match predefined
    # categories offline-plus-one-call, just like the DNS engine.
    live_set = {c.upper() for c in (live_cats or [])}

    for rule in enabled:
        cfg = rule.raw_config or {}

        # Protocol filter
        rule_protos = cfg.get("protocols", [])
        if rule_protos and "ANY_RULE" not in rule_protos:
            if proto_upper not in rule_protos and f"{proto_upper}_RULE" not in rule_protos:
                if not any(p.startswith(proto_upper) for p in rule_protos):
                    continue

        # Identity / location scope — permissive when no input, precise when provided.
        r_users: List[Dict] = cfg.get("users", [])
        r_depts: List[Dict] = cfg.get("departments", [])
        r_groups: List[Dict] = cfg.get("groups", [])
        r_locs: List[Dict] = cfg.get("locations", [])
        if r_users or r_depts or r_groups or r_locs:
            scoped_rules.append(cfg.get("name", "Unknown Rule"))
        if r_users and user_name and not _name_in_list(user_name, r_users):
            continue
        if r_depts and dept_name and not _name_in_list(dept_name, r_depts):
            continue
        if r_groups and group_name and not _name_in_list(group_name, r_groups):
            continue
        if r_locs and location_name and not _name_in_list(location_name, r_locs):
            continue

        rule_cats = cfg.get("url_categories", [])
        if not rule_cats:
            # No category constraint — wildcard rule
            check.matched = True
            check.rule_name = cfg.get("name", "Unknown Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched URL filter rule "{check.rule_name}" (no category constraint — applies to all URLs)'
            break

        matched_cat = None
        matched_via_live = False
        has_predefined = False
        for cat_id in rule_cats:
            cid = str(cat_id)
            cat_cfg = categories.get(cid)
            if cat_cfg and cat_cfg.get("custom_category"):
                # Custom category — resolve against its stored URL list offline.
                if _url_in_category(hostname, cat_cfg):
                    matched_cat = cat_cfg.get("configured_name") or cid
                    break
                continue
            # Predefined category (resolved as non-custom, or a bare predefined name).
            if live_cats is not None:
                if cid.upper() in live_set:
                    matched_cat = cid
                    matched_via_live = True
                    break
            else:
                # No live lookup available — can't evaluate this predefined category.
                has_predefined = True

        if matched_cat:
            check.matched = True
            check.rule_name = cfg.get("name", "Unknown Rule")
            check.action = cfg.get("action", "ALLOW")
            check.category = matched_cat
            via = "live category" if matched_via_live else "category"
            check.reason = f'Matched URL filter rule "{check.rule_name}" via {via} "{matched_cat}"'
            break

        if has_predefined:
            predefined_rules.append(cfg.get("name", "Unknown Rule"))

    def _fmt(names: List[str]) -> str:
        return ", ".join(f'"{n}"' for n in names[:5]) + (f" +{len(names)-5} more" if len(names) > 5 else "")

    # Predefined-category rules that couldn't be resolved offline — surface even on a match,
    # since one of them could be the real winner ahead of the matched rule.
    if predefined_rules:
        if check.matched:
            check.caveats.append(
                "Higher-priority rules using predefined URL categories were skipped offline "
                "(a live category lookup may change this result): " + _fmt(predefined_rules)
            )
        else:
            check.caveats.append(
                "Rules using predefined URL categories cannot be evaluated offline: " + _fmt(predefined_rules)
            )

    # Scoped rules evaluated permissively because no identity context was supplied.
    if scoped_rules and not has_identity:
        check.caveats.append(
            "URL rules scoped to users/departments/groups/locations were evaluated permissively — "
            "provide identity context (user/department/group/location) for a precise result: "
            + _fmt(scoped_rules)
        )

    if not check.matched:
        check.reason = (
            "No custom URL category matched this hostname" if predefined_rules
            else "No URL filter rule matched this hostname"
        )

    return check


# ---------------------------------------------------------------------------
# ZIA SSL Inspection evaluation
# ---------------------------------------------------------------------------

def _eval_ssl_inspection(
    tenant_id: int, dest: str, protocol: str,
    cloud_app: Optional[str] = None,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA SSL Inspection")

    if protocol.upper() not in ("HTTPS", "SSL", "TLS", "HTTP"):
        check.action = "N/A"
        check.reason = f"SSL inspection does not apply to {protocol} traffic"
        return check

    hostname = _strip_url(dest)

    with get_session() as s:
        rules = s.query(ZIAResource).filter_by(
            tenant_id=tenant_id, resource_type="ssl_inspection_rule", is_deleted=False
        ).all()
        url_categories = _resolve_url_categories(tenant_id, s)

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    non_default = [r for r in enabled if not (r.raw_config or {}).get("default_rule")]
    default_rules = [r for r in enabled if (r.raw_config or {}).get("default_rule")]
    non_default.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))
    enabled = non_default + default_rules

    predefined_skipped: List[str] = []

    for rule in enabled:
        cfg = rule.raw_config or {}
        url_cats: List[str] = cfg.get("url_categories", [])
        cloud_apps: List[str] = [str(a) for a in cfg.get("cloud_applications", []) if a]
        users: List[Dict] = cfg.get("users", [])
        depts: List[Dict] = cfg.get("departments", [])
        groups: List[Dict] = cfg.get("groups", [])
        locs: List[Dict] = cfg.get("locations", [])

        # Evaluate url_categories — resolve custom ones, skip predefined
        cat_matched = False
        has_predefined = False
        if url_cats:
            for cat_id in url_cats:
                cat_cfg = url_categories.get(str(cat_id))
                if cat_cfg is None:
                    has_predefined = True
                    continue
                if cat_cfg.get("custom_category"):
                    if _url_in_category(hostname, cat_cfg):
                        cat_matched = True
                        break
                else:
                    has_predefined = True
            if not cat_matched:
                if has_predefined:
                    predefined_skipped.append(cfg.get("name", "?"))
                continue

        # cloud_applications constraint (only evaluated when no url_cats matched)
        if cloud_apps and not cat_matched:
            if not cloud_app or cloud_app.upper() not in [a.upper() for a in cloud_apps]:
                if not url_cats:
                    predefined_skipped.append(cfg.get("name", "?"))
                continue

        # identity constraints (permissive if not provided)
        if users and user_name and not _name_in_list(user_name, users):
            continue
        if depts and dept_name and not _name_in_list(dept_name, depts):
            continue
        if groups and group_name and not _name_in_list(group_name, groups):
            continue
        if locs and location_name and not _name_in_list(location_name, locs):
            continue

        action_cfg = cfg.get("action", {})
        action_type = action_cfg.get("type", "DECRYPT") if isinstance(action_cfg, dict) else str(action_cfg)
        check.matched = True
        check.rule_name = cfg.get("name", "Unknown Rule")
        check.action = action_type
        check.reason = f'Matched SSL rule "{check.rule_name}" (order {cfg.get("order", "?")}) → {action_type}'
        break

    if not check.matched:
        check.action = "DECRYPT"
        check.reason = "No SSL bypass rule matched — traffic will be decrypted (default)"
        if predefined_skipped:
            check.caveats.append(
                "Rules using predefined URL categories cannot be evaluated offline: "
                + ", ".join(f'"{n}"' for n in predefined_skipped[:5])
                + (f" +{len(predefined_skipped)-5} more" if len(predefined_skipped) > 5 else "")
            )

    return check


# ---------------------------------------------------------------------------
# ZIA Cloud App Control evaluation
# ---------------------------------------------------------------------------

def _eval_cloud_app_control(
    tenant_id: int,
    cloud_app: Optional[str] = None,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA Cloud App Control")

    if not cloud_app:
        check.reason = "No cloud application specified — cloud app control not evaluated"
        return check

    with get_session() as s:
        rules = s.query(ZIAResource).filter_by(
            tenant_id=tenant_id, resource_type="cloud_app_control_rule", is_deleted=False
        ).all()

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    enabled.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))

    app_upper = cloud_app.upper()

    for rule in enabled:
        cfg = rule.raw_config or {}
        applications = [str(a).upper() for a in cfg.get("applications", [])]
        if not applications or app_upper not in applications:
            continue

        users: List[Dict] = cfg.get("users", [])
        depts: List[Dict] = cfg.get("departments", [])
        groups: List[Dict] = cfg.get("groups", [])
        locs: List[Dict] = cfg.get("locations", [])

        if users and user_name and not _name_in_list(user_name, users):
            continue
        if depts and dept_name and not _name_in_list(dept_name, depts):
            continue
        if groups and group_name and not _name_in_list(group_name, groups):
            continue
        if locs and location_name and not _name_in_list(location_name, locs):
            continue

        actions: List[str] = cfg.get("actions", [])
        is_block = any("BLOCK" in str(a).upper() for a in actions)
        action = "BLOCK" if is_block else "ALLOW"

        check.matched = True
        check.rule_name = cfg.get("name", "Unknown Rule")
        check.action = action
        check.reason = (
            f'Matched cloud app control rule "{check.rule_name}" '
            f'(type: {cfg.get("type", "?")}) → {action}'
        )
        break

    if not check.matched:
        check.reason = f'No cloud app control rule matched "{cloud_app}"'

    return check


# ---------------------------------------------------------------------------
# ZIA Security Exceptions evaluation
# ---------------------------------------------------------------------------

def _eval_security_exceptions(tenant_id: int, dest: str) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA Security Exceptions")
    hostname = _strip_url(dest)

    with get_session() as s:
        rows = s.query(ZIAResource).filter_by(
            tenant_id=tenant_id, resource_type="allowlist", is_deleted=False
        ).all()

    for row in rows:
        cfg = row.raw_config or {}
        for url in cfg.get("whitelist_urls", []):
            if url and _hostname_matches(hostname, url.strip()):
                check.matched = True
                check.action = "ALLOW"
                check.reason = "Destination is in security exceptions allowlist — bypasses URL filtering"
                return check
        for url in cfg.get("blacklist_urls", []):
            if url and _hostname_matches(hostname, url.strip()):
                check.matched = True
                check.action = "BLOCK"
                check.reason = "Destination is in security exceptions denylist"
                return check

    check.reason = "Destination is not in any security exception list"
    return check


# ---------------------------------------------------------------------------
# ZCC PAC DIRECT-rule evaluation
# ---------------------------------------------------------------------------
#
# These mirror the regex heuristics in api/routers/zcc.py._fetch_pac_bypasses
# (which enumerates a PAC file's DIRECT rules for the traffic-profile
# visualizer) but instead evaluate a concrete destination against them.

_PAC_RFC1918_MAP = {
    "10": "10.0.0.0/8",
    "127": "127.0.0.0/8",
    r"192\.168": "192.168.0.0/16",
    r"172\.1[6789]": "172.16.0.0/12",
    r"172\.2[0-9]": "172.16.0.0/12",
    r"172\.3[01]": "172.16.0.0/12",
    r"169\.254": "169.254.0.0/16",
    r"192\.88\.99": "192.88.99.0/24",
}


def _mask_to_prefix(mask: str) -> int:
    try:
        return sum(bin(int(p)).count("1") for p in mask.split("."))
    except Exception:
        return 0


def _fetch_pac_content(pac_url: Optional[str], timeout: int = 4) -> Optional[str]:
    """Fetch a PAC file's contents. Returns None on any failure.

    PAC URLs originate from Zscaler cloud configuration and are treated as
    trusted, mirroring api/routers/zcc.py._fetch_pac_bypasses.
    """
    if not pac_url or not pac_url.startswith("http"):
        return None
    try:
        req = urllib.request.Request(pac_url, headers={"User-Agent": "zs-config/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _collect_pac_arrays(content_nc: str) -> tuple:
    """Parse JS host-pattern arrays from PAC source.

    Handles the common real-world pattern where bypass hosts are declared in
    arrays and combined with [].concat(...):
        var bypassX = ["a.com", "*.b.com"];
        var bypassAll = [].concat(bypassX, bypassY);

    Returns (literal_arrays, resolved_arrays) where literal_arrays maps each
    directly-declared array name to its string patterns, and resolved_arrays
    additionally maps every [].concat(...) name to the union of its members.
    """
    literal: Dict[str, List[str]] = {}
    # var NAME = [ ...quoted strings... ];  (body has no ']'; spans newlines)
    decl_re = re.compile(r"var\s+(\w+)\s*=\s*\[([^\]]*)\]\s*;")
    for m in decl_re.finditer(content_nc):
        name, body = m.group(1), m.group(2)
        literal[name] = [s for s in re.findall(r'"([^"]*)"', body) if s]

    resolved: Dict[str, List[str]] = dict(literal)
    # var NAME = [].concat( a, b, c );  (args are bare identifiers)
    concat_re = re.compile(r"var\s+(\w+)\s*=\s*\[\]\s*\.concat\s*\(([^)]*)\)")
    for m in concat_re.finditer(content_nc):
        name, args = m.group(1), m.group(2)
        combined: List[str] = []
        for ref in re.findall(r"[A-Za-z_]\w*", args):
            combined.extend(literal.get(ref, []))
        resolved[name] = combined
    return literal, resolved


def _pac_direct_match(
    content: str, dest: str, port: int, protocol: str
) -> Optional[Dict[str, str]]:
    """Evaluate a destination against a PAC file's DIRECT (bypass) rules.

    Returns {"rule": ..., "detail": ...} for the first DIRECT rule the
    destination satisfies, or None. Only uncommented lines are considered.
    """
    if not content:
        return None

    content_nc = re.sub(r"//[^\n]*", "", content)
    hostname = _strip_url(dest)
    dest_is_ip = _is_ip(dest)

    # ── 1. RFC1918 / private-IP regex variable → DIRECT ──────────────────────
    if dest_is_ip:
        var_regex_re = re.compile(r"var\s+(\w+)\s*=\s*/([^/\n]{10,})/[gimy]*\s*;")
        for m in var_regex_re.finditer(content_nc):
            varname, regex_body = m.group(1), m.group(2)
            if not re.search(r"\b(192|172|10|127|169)\b", regex_body):
                continue
            test_re = re.compile(rf"\b{re.escape(varname)}\.test\s*\(")
            near_direct = any(
                "DIRECT" in content_nc[tm.start(): min(len(content_nc), tm.end() + 400)]
                for tm in test_re.finditer(content_nc)
            )
            if not near_direct:
                continue
            for pat, cidr in _PAC_RFC1918_MAP.items():
                if pat in regex_body and _ip_in_cidr(dest, cidr):
                    return {"rule": f"RFC1918 private IP ({cidr})",
                            "detail": "PAC private-IP regex → DIRECT"}

    # ── 2. isInNet(x, "ip", "mask") → DIRECT ─────────────────────────────────
    if dest_is_ip:
        innet_re = re.compile(r'isInNet\s*\([^,)]+,\s*"([0-9.]+)"\s*,\s*"([0-9.]+)"\s*\)')
        for m in innet_re.finditer(content_nc):
            ip, mask = m.group(1), m.group(2)
            ctx = content_nc[m.start(): min(len(content_nc), m.end() + 300)]
            if "DIRECT" not in ctx:
                continue
            cidr = f"{ip}/{_mask_to_prefix(mask)}"
            if _ip_in_cidr(dest, cidr):
                return {"rule": f"isInNet {cidr}", "detail": "PAC isInNet → DIRECT"}

    # ── 3. Explicit host == "..." → DIRECT ───────────────────────────────────
    host_eq_re = re.compile(r'host\s*==\s*"([^"]+)"')
    for m in host_eq_re.finditer(content_nc):
        h = _strip_url(m.group(1))
        ctx = content_nc[m.start(): min(len(content_nc), m.end() + 200)]
        if "DIRECT" in ctx and hostname == h:
            return {"rule": f'host == "{m.group(1)}"', "detail": "PAC host match → DIRECT"}

    # ── 4. shExpMatch(host, "pattern") → DIRECT ──────────────────────────────
    shexp_re = re.compile(r'shExpMatch\s*\(\s*host\s*,\s*"([^"]+)"\s*\)')
    for m in shexp_re.finditer(content_nc):
        pattern = m.group(1)
        if "example" in pattern.lower():
            continue
        ctx = content_nc[m.start(): min(len(content_nc), m.end() + 200)]
        if "DIRECT" in ctx and _hostname_matches(hostname, pattern):
            return {"rule": f'shExpMatch "{pattern}"', "detail": "PAC shExpMatch → DIRECT"}

    # ── 4b. Array-based shExpMatch host lists → DIRECT ────────────────────────
    # PACs commonly loop a bypass array against the host, e.g.:
    #   for (i...) if (shExpMatch(h, bypassAllHosts[i])) return "DIRECT";
    # Resolve the looped array (through [].concat) to its patterns and test each.
    literal_arrays, resolved_arrays = _collect_pac_arrays(content_nc)
    loop_re = re.compile(r'shExpMatch\s*\([^,]+,\s*(\w+)\s*\[')
    for m in loop_re.finditer(content_nc):
        arrvar = m.group(1)
        ctx = content_nc[m.start(): min(len(content_nc), m.end() + 300)]
        if "DIRECT" not in ctx:
            continue
        for pat in resolved_arrays.get(arrvar, []):
            if _hostname_matches(hostname, pat):
                src = next((n for n, pats in literal_arrays.items() if pat in pats), arrvar)
                return {"rule": f'shExpMatch list "{pat}" ({src})',
                        "detail": "PAC array bypass → DIRECT"}

    # ── 5. isPlainHostName → DIRECT ──────────────────────────────────────────
    if not dest_is_ip and "." not in hostname:
        for m in re.finditer(r"isPlainHostName\s*\(", content_nc):
            ctx = content_nc[m.start(): min(len(content_nc), m.end() + 300)]
            if "DIRECT" in ctx:
                return {"rule": "Plain hostname (unqualified)",
                        "detail": "PAC isPlainHostName → DIRECT"}

    # ── 6. Non-HTTP/S protocols → DIRECT ──────────────────────────────────────
    if protocol.upper() not in ("HTTP", "HTTPS", "SSL", "TLS"):
        if re.search(r"url\.substring.*!=.*https?.*DIRECT", content_nc, re.DOTALL):
            return {"rule": f"Non-HTTP/S protocol ({protocol})",
                    "detail": "PAC protocol check → DIRECT"}

    return None


def _cached_pac_content(tenant_id: int, pac_url: str, session) -> Optional[str]:
    """Return the imported pac_content for a PAC URL, or None if not cached.

    Joins on the ZIA pac_file resource whose pacUrl matches the ZCC profile's
    PAC URL. Requires a prior ZIA import with content capture (see
    zia_client.list_pac_files_with_content).
    """
    if not pac_url:
        return None
    rows = session.query(ZIAResource).filter_by(
        tenant_id=tenant_id, resource_type="pac_file", is_deleted=False
    ).all()
    for r in rows:
        cfg = r.raw_config or {}
        if cfg.get("pacUrl") == pac_url and cfg.get("pacContent"):
            return cfg.get("pacContent")
    return None


def _eval_pac_bypass(
    tenant_id: int, dest: str, port: int, protocol: str, zcc_profile: Optional[str]
) -> Optional[PolicyCheck]:
    """Check whether the destination is sent DIRECT by the active ZCC PAC file.

    Resolves both the forwarding-profile PAC URL and the app-profile PAC URL
    (mirroring api/routers/zcc.py get_traffic_profile). Prefers PAC content
    captured in the local cache (imported pac_file resources) and falls back to a
    live fetch only when the content isn't cached. Returns a BYPASS PolicyCheck on
    the first DIRECT match, or None when no profile is selected, no PAC applies,
    or nothing matches.
    """
    if not zcc_profile:
        return None

    with get_session() as s:
        policies = s.query(ZCCResource).filter_by(
            tenant_id=tenant_id, resource_type="web_policy", is_deleted=False
        ).all()
        raw_policy = None
        for p in policies:
            if (p.raw_config or {}).get("name") == zcc_profile:
                raw_policy = p.raw_config or {}
                break
        if raw_policy is None:
            return None
        raw_fp = _resolve_forwarding_profile(tenant_id, zcc_profile, s)

        app_pac_url = raw_policy.get("pac_url") or raw_policy.get("pacUrl") or None
        fp_pac_url = None
        if raw_fp:
            actions = (raw_fp.get("forwardingProfileActions")
                       or raw_fp.get("forwarding_profile_actions") or [])
            if actions and isinstance(actions[0], dict):
                spd = (actions[0].get("systemProxyData")
                       or actions[0].get("system_proxy_data") or {})
                fp_pac_url = (spd.get("pacURL") or spd.get("pac_u_r_l")
                              or spd.get("pac_url") or None)

        # (pac_url, label, cached_content) — resolve cache inside the session.
        sources = [
            (url, label, _cached_pac_content(tenant_id, url, s))
            for url, label in ((fp_pac_url, "forwarding profile"), (app_pac_url, "app profile"))
            if url
        ]

    for pac_url, label, cached in sources:
        content = cached or _fetch_pac_content(pac_url)
        if not content:
            continue
        match = _pac_direct_match(content, dest, port, protocol)
        if match:
            check = PolicyCheck(engine="ZCC Bypass")
            check.matched = True
            check.action = "BYPASS"
            check.rule_name = match["rule"]
            check.reason = (
                f'Destination matches PAC DIRECT rule ({match["rule"]}) in the '
                f'{label} PAC file — bypasses ZCC tunnel, goes direct to internet'
            )
            if not cached:
                check.caveats.append(
                    "PAC content was fetched live (not in local cache) — re-import "
                    "ZIA for this tenant to cache it for offline evaluation"
                )
            return check

    return None


# ---------------------------------------------------------------------------
# ZCC Bypass evaluation
# ---------------------------------------------------------------------------

def _eval_zcc_bypass(
    tenant_id: int, dest: str, port: int, protocol: str,
    zcc_profile: Optional[str] = None,
) -> PolicyCheck:
    check = PolicyCheck(engine="ZCC Bypass")
    dest_is_ip = _is_ip(dest)

    with get_session() as s:
        policies = s.query(ZCCResource).filter_by(
            tenant_id=tenant_id, resource_type="web_policy", is_deleted=False
        ).all()
        app_services = s.query(ZCCResource).filter_by(
            tenant_id=tenant_id, resource_type="web_app_service", is_deleted=False
        ).all()

    if zcc_profile:
        filtered = [r for r in policies if (r.raw_config or {}).get("name") == zcc_profile]
        if filtered:
            policies = filtered

    for policy in policies:
        cfg = policy.raw_config or {}
        policy_name = cfg.get("name", "Unknown Policy")
        ext = cfg.get("policyExtension") or {}

        # IP/CIDR packet tunnel exclusions
        exclude_list = str(ext.get("packetTunnelExcludeList") or "")
        if exclude_list and dest_is_ip:
            for cidr in [c.strip() for c in exclude_list.split(",") if c.strip()]:
                try:
                    if "/" in cidr:
                        if _ip_in_cidr(dest, cidr):
                            check.matched = True
                            check.action = "BYPASS"
                            check.rule_name = policy_name
                            check.reason = f'Destination matches ZCC IP exclusion "{cidr}" in profile "{policy_name}" — bypasses tunnel'
                            return check
                    elif dest == cidr:
                        check.matched = True
                        check.action = "BYPASS"
                        check.rule_name = policy_name
                        check.reason = f'Destination matches ZCC IP exclusion "{cidr}" in profile "{policy_name}" — bypasses tunnel'
                        return check
                except Exception:
                    pass

        # Port-based bypasses (format: "port:dest" e.g. "3389:*")
        port_bypasses = str(ext.get("sourcePortBasedBypasses") or "")
        if port_bypasses:
            for bypass in [b.strip() for b in port_bypasses.split(",") if b.strip()]:
                try:
                    bypass_port = int(bypass.split(":")[0])
                    if bypass_port == port:
                        check.matched = True
                        check.action = "BYPASS"
                        check.rule_name = policy_name
                        check.reason = f'Port {port} matches ZCC port bypass "{bypass}" in profile "{policy_name}" — bypasses tunnel'
                        return check
                except (ValueError, IndexError):
                    pass

    # App service (split-tunnel) bypass
    if dest_is_ip:
        for svc in app_services:
            cfg = svc.raw_config or {}
            app_name = cfg.get("app_name", "Unknown App")
            for blob_str in cfg.get("app_data_blob", []):
                try:
                    blob = ast.literal_eval(blob_str) if isinstance(blob_str, str) else blob_str
                    blob_proto = str(blob.get("proto", "")).upper()
                    blob_ports = [int(p) for p in str(blob.get("port", "")).split(",") if p.strip().isdigit()]
                    blob_ips = [ip.strip() for ip in str(blob.get("ipaddr") or blob.get("ip_addr", "")).split(",") if ip.strip()]
                    proto_match = not blob_proto or protocol.upper().startswith(blob_proto.rstrip("S"))
                    port_match = not blob_ports or port in blob_ports
                    ip_match = any(
                        (_ip_in_cidr(dest, cidr) if "/" in cidr else dest == cidr)
                        for cidr in blob_ips
                        if cidr
                    )
                    if proto_match and port_match and ip_match:
                        check.matched = True
                        check.action = "BYPASS"
                        check.rule_name = app_name
                        check.reason = f'Destination matches ZCC app service bypass for "{app_name}" — may bypass tunnel'
                        return check
                except Exception:
                    pass

    # No explicit exclusion / port / app-service bypass matched — fall back to
    # the active PAC file's DIRECT rules (requires a live PAC fetch).
    pac_check = _eval_pac_bypass(tenant_id, dest, port, protocol, zcc_profile)
    if pac_check is not None:
        return pac_check

    check.reason = "No ZCC bypass criteria matched — traffic will be tunneled through ZCC"
    return check


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_BLOCK_ACTIONS = {"BLOCK", "BLOCK_DROP", "BLOCK_ICMP", "BLOCK_RESET", "BLOCK_BYPASS"}


_NC_INT = {"on": 0, "vpn": 1, "off": 2}


def _resolve_forwarding_profile(tenant_id: int, zcc_profile: str, session) -> Optional[dict]:
    """Resolve the forwarding profile raw_config for a ZCC app profile name.

    Mirrors the logic in api/routers/zcc.py get_traffic_profile:
    1. Find the web_policy by name
    2. Use onNetPolicy (embedded by direct HTTP import) if present
    3. Fall back to forwardingProfileId lookup in forwarding_profile records
    """
    policy_row = session.query(ZCCResource).filter_by(
        tenant_id=tenant_id, resource_type="web_policy", is_deleted=False
    ).all()

    raw_policy = None
    for p in policy_row:
        if (p.raw_config or {}).get("name") == zcc_profile:
            raw_policy = p.raw_config or {}
            break
    if raw_policy is None:
        return None

    # Prefer onNetPolicy (embedded forwarding profile from direct HTTP import)
    raw_fp = raw_policy.get("onNetPolicy") or None
    if raw_fp:
        return raw_fp

    # Fallback: look up forwarding_profile record by forwardingProfileId
    fp_id = str(raw_policy.get("forwardingProfileId") or raw_policy.get("forwarding_profile_id") or "")
    if not fp_id:
        return None
    fp_id_candidates = [fp_id, fp_id + ".0"] if not fp_id.endswith(".0") else [fp_id, fp_id[:-2]]
    fp_row = session.query(ZCCResource).filter(
        ZCCResource.tenant_id == tenant_id,
        ZCCResource.resource_type == "forwarding_profile",
        ZCCResource.zcc_id.in_(fp_id_candidates),
        ZCCResource.is_deleted == False,  # noqa: E712
    ).first()
    return fp_row.raw_config if fp_row else None


def _eval_network_context(tenant_id: int, zcc_profile: Optional[str], network_context: str) -> Optional[PolicyCheck]:
    """Return a PolicyCheck if ZCC is inactive for this network context.

    Uses the same forwarding profile resolution as the ZCC traffic profile
    visualizer (onNetPolicy → forwardingProfileId fallback).
    action_type=0 (None/Disabled) means ZCC is off for that network context.
    """
    nc = _NC_INT.get(network_context)
    if nc is None or not zcc_profile:
        return None

    with get_session() as s:
        raw_fp = _resolve_forwarding_profile(tenant_id, zcc_profile, s)

    if not raw_fp:
        return None

    fp_name = raw_fp.get("name", zcc_profile)
    actions = (
        raw_fp.get("forwarding_profile_actions")
        or raw_fp.get("forwardingProfileActions")
        or raw_fp.get("fp_actions")
        or []
    )
    for action in actions:
        nt = action.get("network_type") if action.get("network_type") is not None else action.get("networkType")
        at = action.get("action_type") if action.get("action_type") is not None else action.get("actionType")
        if nt is None or at is None:
            continue
        if int(nt) == nc and int(at) == 0:
            check = PolicyCheck(engine="ZCC Network Context")
            check.matched = True
            check.action = "BYPASS"
            ctx_label = {"on": "On Trusted Network", "vpn": "VPN Trusted Network", "off": "Off Trusted Network"}.get(network_context, network_context)
            check.rule_name = fp_name
            check.reason = f'ZCC client is inactive on "{ctx_label}" per forwarding profile "{fp_name}" — traffic goes direct'
            return check
    return None


def simulate(
    tenant_id: int, destination: str, port: int, protocol: str,
    nw_application: Optional[str] = None,
    app_service_group: Optional[str] = None,
    cloud_app: Optional[str] = None,
    zcc_profile: Optional[str] = None,
    src_ip: Optional[str] = None,
    user_name: Optional[str] = None,
    dept_name: Optional[str] = None,
    group_name: Optional[str] = None,
    location_name: Optional[str] = None,
    network_context: Optional[str] = None,
) -> SimulationResult:
    dest = destination.strip()

    # Check if ZCC is inactive for this network context (actionType==3 = bypass)
    if network_context:
        nc_check = _eval_network_context(tenant_id, zcc_profile, network_context)
        if nc_check:
            return SimulationResult(
                destination=dest, port=port, protocol=protocol,
                zcc_bypass=nc_check,
                zpa=PolicyCheck(engine="ZPA", reason="ZCC inactive — ZPA not evaluated"),
                zia_firewall=PolicyCheck(engine="ZIA Firewall", reason="ZCC inactive — ZIA not evaluated"),
                zia_dns=PolicyCheck(engine="ZIA DNS", reason="ZCC inactive — ZIA not evaluated"),
                zia_url=PolicyCheck(engine="ZIA URL Filter", reason="ZCC inactive — ZIA not evaluated"),
                zia_ssl=PolicyCheck(engine="ZIA SSL", reason="ZCC inactive — ZIA not evaluated"),
                zia_cloud_app=PolicyCheck(engine="ZIA Cloud App", reason="ZCC inactive — ZIA not evaluated"),
                zia_exceptions=PolicyCheck(engine="ZIA Exceptions", reason="ZCC inactive — ZIA not evaluated"),
                verdict="ZCC_INACTIVE",
                verdict_label=nc_check.reason,
            )

    # Live ZIA url_lookup for res_categories evaluation (DNS rules)
    live_cats = _zia_url_lookup(tenant_id, dest) if not _is_ip(dest) else None

    zcc_bypass = _eval_zcc_bypass(tenant_id, dest, port, protocol, zcc_profile)
    zpa = _eval_zpa(tenant_id, dest, port, protocol)
    zia_fw = _eval_zia_firewall(
        tenant_id, dest, port, protocol,
        nw_application, app_service_group,
        src_ip, user_name, dept_name, group_name, location_name,
    )
    zia_dns = _eval_zia_dns(tenant_id, dest, port, protocol, live_cats)
    zia_url = _eval_zia_url(
        tenant_id, dest, port, protocol,
        user_name, dept_name, group_name, location_name,
        live_cats=live_cats,
    )
    zia_ssl = _eval_ssl_inspection(
        tenant_id, dest, protocol,
        cloud_app, user_name, dept_name, group_name, location_name,
    )
    zia_cloud_app = _eval_cloud_app_control(
        tenant_id, cloud_app, user_name, dept_name, group_name, location_name,
    )
    zia_exceptions = _eval_security_exceptions(tenant_id, dest)

    # Determine verdict.
    #
    # ZCC (on-device) and ZPA are decided before traffic reaches ZIA. The ZIA
    # engines are then ranked to match Zscaler's real enforcement order for a
    # transaction: DNS Control → Cloud Firewall → SSL Inspection (decrypt gate,
    # never a block) → Cloud App Control → Security Exceptions (URL allow/deny
    # override) → URL Filtering. So when more than one engine would block, the
    # reported block is the one ZIA would actually enforce first.
    if zcc_bypass.matched and zcc_bypass.action == "BYPASS":
        verdict = "ZCC_BYPASS"
        verdict_label = f'Traffic bypasses ZCC tunnel — goes direct to internet via "{zcc_bypass.rule_name}"'
    elif zpa.matched:
        verdict = "ZPA"
        verdict_label = f'Routed through ZPA → "{zpa.rule_name}"'
    elif zia_dns.matched and (zia_dns.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_DNS"
        verdict_label = f'Blocked by ZIA DNS Filter → "{zia_dns.rule_name}"'
    elif zia_fw.matched and (zia_fw.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_FIREWALL"
        verdict_label = f'Blocked by ZIA Firewall → "{zia_fw.rule_name}"'
    elif zia_cloud_app.matched and (zia_cloud_app.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_CLOUDAPP"
        verdict_label = f'Blocked by ZIA Cloud App Control → "{zia_cloud_app.rule_name}"'
    elif zia_url.matched and (zia_url.action or "").upper() in _BLOCK_ACTIONS and not (zia_exceptions.matched and zia_exceptions.action == "ALLOW"):
        verdict = "ZIA_BLOCK_URL"
        verdict_label = f'Blocked by ZIA URL Filter → "{zia_url.rule_name}"'
    else:
        verdict = "ZIA_ALLOW"
        verdict_label = "Allowed through ZIA to internet"

    return SimulationResult(
        destination=dest,
        port=port,
        protocol=protocol,
        zcc_bypass=zcc_bypass,
        zpa=zpa,
        zia_firewall=zia_fw,
        zia_dns=zia_dns,
        zia_url=zia_url,
        zia_ssl=zia_ssl,
        zia_cloud_app=zia_cloud_app,
        zia_exceptions=zia_exceptions,
        verdict=verdict,
        verdict_label=verdict_label,
    )
