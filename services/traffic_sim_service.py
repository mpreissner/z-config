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
"""

import fnmatch
import ipaddress
import re
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
    verdict: str          # ZCC_BYPASS | ZPA | ZIA_ALLOW | ZIA_BLOCK_FIREWALL | ZIA_BLOCK_DNS | ZIA_BLOCK_URL | ZIA_BLOCK_CLOUDAPP | INTERNET
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

    matched_app = None
    for app in apps:
        cfg = app.raw_config or {}
        if not cfg.get("enabled", True):
            continue
        domain_names: List[str] = cfg.get("domain_names", [])
        tcp_ranges: List[Dict] = cfg.get("tcp_port_range", [])
        udp_ranges: List[Dict] = cfg.get("udp_port_range", [])

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
        check.matched = True
        check.rule_name = cfg.get("name", "Unknown App Segment")
        check.action = "ALLOW"
        check.reason = f'Destination matches ZPA application segment "{check.rule_name}"'
        check.caveats = ["ZPA access policy rules not evaluated — assume access allowed if segment matches"]
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

def _eval_zia_dns(tenant_id: int, dest: str, port: int, protocol: str) -> PolicyCheck:
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
        has_dest = bool(dest_addrs or dest_ip_groups_ref or dest_ip_cats or res_cats)

        if has_dest:
            dest_matched = False
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
            # dest_ip_categories / res_categories are predefined ZIA IP categories
            # (e.g. OFFICE_365, GLOBAL_INT_ZOOM). We cannot resolve these offline,
            # so skip the rule rather than falsely matching every hostname.
            if dest_ip_cats or res_cats:
                check.caveats.append(
                    f'Rule "{cfg.get("name")}" skipped offline — uses predefined IP categories '
                    f'({", ".join(set(dest_ip_cats + res_cats))}) that require a live ZIA lookup'
                )
                continue
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


def _eval_zia_url(tenant_id: int, dest: str, port: int, protocol: str) -> PolicyCheck:
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

    predefined_rules: List[str] = []

    for rule in enabled:
        cfg = rule.raw_config or {}

        # Protocol filter
        rule_protos = cfg.get("protocols", [])
        if rule_protos and "ANY_RULE" not in rule_protos:
            if proto_upper not in rule_protos and f"{proto_upper}_RULE" not in rule_protos:
                if not any(p.startswith(proto_upper) for p in rule_protos):
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
        has_predefined = False
        for cat_id in rule_cats:
            cat_cfg = categories.get(str(cat_id))
            if cat_cfg is None:
                continue
            if cat_cfg.get("custom_category"):
                if _url_in_category(hostname, cat_cfg):
                    matched_cat = cat_cfg.get("configured_name") or cat_id
                    break
            else:
                # Predefined category — can't evaluate offline
                has_predefined = True

        if matched_cat:
            check.matched = True
            check.rule_name = cfg.get("name", "Unknown Rule")
            check.action = cfg.get("action", "ALLOW")
            check.category = matched_cat
            check.reason = f'Matched URL filter rule "{check.rule_name}" via category "{matched_cat}"'
            break

        if has_predefined:
            predefined_rules.append(cfg.get("name", "Unknown Rule"))

    if not check.matched:
        if predefined_rules:
            check.reason = "No custom URL category matched this hostname"
            check.caveats.append(
                f"Rules with predefined categories cannot be evaluated offline: "
                + ", ".join(f'"{r}"' for r in predefined_rules[:5])
                + (f" +{len(predefined_rules)-5} more" if len(predefined_rules) > 5 else "")
            )
        else:
            check.reason = "No URL filter rule matched this hostname"

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

    check.reason = "No ZCC bypass criteria matched — traffic will be tunneled through ZCC"
    return check


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_BLOCK_ACTIONS = {"BLOCK", "BLOCK_DROP", "BLOCK_ICMP", "BLOCK_RESET", "BLOCK_BYPASS"}


_NC_INT = {"on": 1, "vpn": 2, "off": 0}


def _eval_network_context(tenant_id: int, zcc_profile: Optional[str], network_context: str) -> Optional[PolicyCheck]:
    """Return a PolicyCheck if ZCC is inactive (actionType==3) for this network context."""
    nc = _NC_INT.get(network_context)
    if nc is None:
        return None
    with get_session() as s:
        fps = s.query(ZCCResource).filter_by(
            tenant_id=tenant_id, resource_type="forwarding_profile", is_deleted=False
        ).all()
        policies = s.query(ZCCResource).filter_by(
            tenant_id=tenant_id, resource_type="web_policy", is_deleted=False
        ).all()

    # If a specific ZCC profile is requested, find its forwarding profile id
    fp_ids: set = set()
    if zcc_profile:
        for p in policies:
            cfg = p.raw_config or {}
            if cfg.get("name") == zcc_profile:
                fpid = cfg.get("forwardingProfileId") or cfg.get("forwarding_profile_id")
                if fpid:
                    fp_ids.add(str(fpid))

    for fp in fps:
        cfg = fp.raw_config or {}
        if fp_ids and str(cfg.get("id", "")) not in fp_ids:
            continue
        fp_name = cfg.get("name", "")
        for action in (cfg.get("fpActions") or cfg.get("fp_actions") or []):
            nt = action.get("networkType") or action.get("network_type")
            at = action.get("actionType") or action.get("action_type")
            if nt is not None and int(nt) == nc and at is not None and int(at) == 3:
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

    zcc_bypass = _eval_zcc_bypass(tenant_id, dest, port, protocol, zcc_profile)
    zpa = _eval_zpa(tenant_id, dest, port, protocol)
    zia_fw = _eval_zia_firewall(
        tenant_id, dest, port, protocol,
        nw_application, app_service_group,
        src_ip, user_name, dept_name, group_name, location_name,
    )
    zia_dns = _eval_zia_dns(tenant_id, dest, port, protocol)
    zia_url = _eval_zia_url(tenant_id, dest, port, protocol)
    zia_ssl = _eval_ssl_inspection(
        tenant_id, dest, protocol,
        cloud_app, user_name, dept_name, group_name, location_name,
    )
    zia_cloud_app = _eval_cloud_app_control(
        tenant_id, cloud_app, user_name, dept_name, group_name, location_name,
    )
    zia_exceptions = _eval_security_exceptions(tenant_id, dest)

    # Determine verdict
    if zcc_bypass.matched and zcc_bypass.action == "BYPASS":
        verdict = "ZCC_BYPASS"
        verdict_label = f'Traffic bypasses ZCC tunnel — goes direct to internet via "{zcc_bypass.rule_name}"'
    elif zpa.matched:
        verdict = "ZPA"
        verdict_label = f'Routed through ZPA → "{zpa.rule_name}"'
    elif zia_fw.matched and (zia_fw.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_FIREWALL"
        verdict_label = f'Blocked by ZIA Firewall → "{zia_fw.rule_name}"'
    elif zia_cloud_app.matched and (zia_cloud_app.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_CLOUDAPP"
        verdict_label = f'Blocked by ZIA Cloud App Control → "{zia_cloud_app.rule_name}"'
    elif zia_dns.matched and (zia_dns.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_DNS"
        verdict_label = f'Blocked by ZIA DNS Filter → "{zia_dns.rule_name}"'
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
