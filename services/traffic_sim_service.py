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

from db.database import get_session
from db.models import ZIAResource, ZPAResource


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
    zpa: PolicyCheck
    zia_firewall: PolicyCheck
    zia_dns: PolicyCheck
    zia_url: PolicyCheck
    verdict: str          # ZPA | ZIA_ALLOW | ZIA_BLOCK_FIREWALL | ZIA_BLOCK_DNS | ZIA_BLOCK_URL | INTERNET
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


def _fw_rule_matches(cfg: Dict, dest: str, port: int, protocol: str,
                     ip_groups: Dict[int, List[str]],
                     nw_services: Dict[int, Dict],
                     nw_svc_groups: Dict[int, List[int]] = None,
                     nw_application: Optional[str] = None) -> bool:
    """Evaluate one firewall rule against the given traffic parameters.

    Returns True if ALL specified constraints match (AND semantics within a rule).
    Empty constraint list = wildcard (matches everything).
    """
    if cfg.get("state", "ENABLED") != "ENABLED":
        return False

    dest_is_ip = _is_ip(dest)
    hostname = _strip_url(dest)

    # ── Destination IP check ──────────────────────────────────────────────
    dest_addrs: List[str] = cfg.get("dest_addresses", [])
    dest_ip_groups: List[Dict] = cfg.get("dest_ip_groups", [])
    dest_ip_cats: List[str] = cfg.get("dest_ip_categories", [])

    has_dest_constraint = bool(dest_addrs or dest_ip_groups or dest_ip_cats)
    if has_dest_constraint:
        dest_matched = False
        if dest_addrs and dest_is_ip:
            dest_matched = _ip_matches_any(dest, dest_addrs)
        if not dest_matched and dest_ip_groups and dest_is_ip:
            for grp in dest_ip_groups:
                gid = grp.get("id")
                if gid and int(gid) in ip_groups:
                    if _ip_matches_any(dest, ip_groups[int(gid)]):
                        dest_matched = True
                        break
        if not dest_matched:
            return False

    # ── Application-layer constraint (nw_applications or app_service_groups) ─
    rule_nw_apps: List[str] = cfg.get("nw_applications", [])
    rule_app_svc_groups: List[Dict] = cfg.get("app_service_groups", [])
    has_port_constraint = bool(cfg.get("nw_services") or cfg.get("nw_service_groups"))
    has_app_constraint = bool(rule_nw_apps or rule_app_svc_groups)

    if has_app_constraint and not has_port_constraint:
        # Rule matches only on application identity — can't evaluate offline without explicit app input
        if nw_application and rule_nw_apps and nw_application.upper() in [a.upper() for a in rule_nw_apps]:
            return True
        return False

    # ── Port / service check ──────────────────────────────────────────────
    rule_services: List[Dict] = cfg.get("nw_services", [])
    rule_svc_groups: List[Dict] = cfg.get("nw_service_groups", [])
    has_svc_constraint = bool(rule_services or rule_svc_groups)

    if has_svc_constraint:
        svc_matched = False
        # Check individual services
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
        # Check service groups (expand group → individual services)
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

    return True


def _eval_zia_firewall(tenant_id: int, dest: str, port: int, protocol: str, nw_application: Optional[str] = None) -> PolicyCheck:
    check = PolicyCheck(engine="ZIA Firewall")

    with get_session() as s:
        rules = (
            s.query(ZIAResource)
            .filter_by(tenant_id=tenant_id, resource_type="firewall_rule", is_deleted=False)
            .all()
        )
        ip_groups = _resolve_ip_dest_groups(tenant_id, s)
        nw_services = _resolve_network_services(tenant_id, s)
        nw_svc_groups = _resolve_network_service_groups(tenant_id, s)

    enabled = [r for r in rules if (r.raw_config or {}).get("state") == "ENABLED"]
    # Default rule has order -1 in ZIA (sentinel for "bottom of list") — always evaluate last
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
        if _fw_rule_matches(cfg, dest, port, protocol, ip_groups, nw_services, nw_svc_groups, nw_application):
            check.matched = True
            check.rule_name = cfg.get("name", "Unknown Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched firewall rule "{check.rule_name}" (order {cfg.get("order", "?")})'
            break

    if not check.matched:
        check.reason = "No firewall rule matched — traffic will hit the default rule"

    # Flag any app-based rules that were skipped
    app_rules = [
        (r.raw_config or {}).get("name", "?")
        for r in enabled
        if ((r.raw_config or {}).get("nw_applications") or (r.raw_config or {}).get("app_service_groups"))
        and not (r.raw_config or {}).get("nw_services")
        and not (r.raw_config or {}).get("nw_service_groups")
    ]
    if app_rules:
        check.caveats.append(
            "Rules using application-layer matching cannot be evaluated offline and were skipped: "
            + ", ".join(f'"{n}"' for n in app_rules[:5])
            + (f" +{len(app_rules)-5} more" if len(app_rules) > 5 else "")
        )

    if not _is_ip(dest):
        check.caveats.append("Destination is a hostname; firewall IP matching may not apply if ZIA resolves DNS differently")

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
    enabled.sort(key=lambda r: (r.raw_config or {}).get("order", 9999))

    for rule in enabled:
        cfg = rule.raw_config or {}
        if cfg.get("default_rule"):
            check.matched = True
            check.rule_name = cfg.get("name", "Default DNS Rule")
            check.action = cfg.get("action", "ALLOW")
            check.reason = f'Matched default DNS rule "{check.rule_name}" (catch-all)'
            break

        dest_addrs: List[str] = cfg.get("dest_addresses", [])
        dest_ip_groups_ref: List[Dict] = cfg.get("dest_ip_groups", [])
        has_dest = bool(dest_addrs or dest_ip_groups_ref)

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
        for url in url_list:
            url = url.strip().lower().lstrip("http://").lstrip("https://").strip("/")
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
# Public API
# ---------------------------------------------------------------------------

_BLOCK_ACTIONS = {"BLOCK", "BLOCK_DROP", "BLOCK_ICMP", "BLOCK_RESET", "BLOCK_BYPASS"}


def simulate(tenant_id: int, destination: str, port: int, protocol: str, nw_application: Optional[str] = None) -> SimulationResult:
    dest = destination.strip()
    zpa = _eval_zpa(tenant_id, dest, port, protocol)
    zia_fw = _eval_zia_firewall(tenant_id, dest, port, protocol, nw_application)
    zia_dns = _eval_zia_dns(tenant_id, dest, port, protocol)
    zia_url = _eval_zia_url(tenant_id, dest, port, protocol)

    # Determine verdict
    if zpa.matched:
        verdict = "ZPA"
        verdict_label = f'Routed through ZPA → "{zpa.rule_name}"'
    elif zia_fw.matched and (zia_fw.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_FIREWALL"
        verdict_label = f'Blocked by ZIA Firewall → "{zia_fw.rule_name}"'
    elif zia_dns.matched and (zia_dns.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_DNS"
        verdict_label = f'Blocked by ZIA DNS Filter → "{zia_dns.rule_name}"'
    elif zia_url.matched and (zia_url.action or "").upper() in _BLOCK_ACTIONS:
        verdict = "ZIA_BLOCK_URL"
        verdict_label = f'Blocked by ZIA URL Filter → "{zia_url.rule_name}"'
    else:
        verdict = "ZIA_ALLOW"
        verdict_label = "Allowed through ZIA to internet"

    return SimulationResult(
        destination=dest,
        port=port,
        protocol=protocol,
        zpa=zpa,
        zia_firewall=zia_fw,
        zia_dns=zia_dns,
        zia_url=zia_url,
        verdict=verdict,
        verdict_label=verdict_label,
    )
