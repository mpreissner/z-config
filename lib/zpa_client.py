from typing import Dict, List, Optional

from zscaler import ZscalerClient

from .auth import ZscalerAuth


def _unwrap(result, resp, err):
    if err:
        raise RuntimeError(str(err))
    return result


def _to_dicts(items) -> list:
    if not items:
        return []
    return [
        i if isinstance(i, dict) else (i.as_dict() if hasattr(i, 'as_dict') else vars(i))
        for i in items
    ]


def _to_dict(item) -> dict:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, 'as_dict'):
        return item.as_dict()
    return vars(item)


class ZPAClient:
    """SDK adapter for the Zscaler Private Access (ZPA) API.

    Wraps zscaler-sdk-python behind the same method signatures as the
    original hand-rolled HTTP client so all callers remain unchanged.
    """

    def __init__(
        self,
        auth: ZscalerAuth,
        customer_id: str,
        oneapi_base_url: str = "https://api.zsapi.net",
    ):
        self.auth = auth
        self.customer_id = customer_id
        self._sdk = ZscalerClient({
            "clientId": auth.client_id,
            "clientSecret": auth.client_secret,
            "vanityDomain": auth.vanity_domain,
            "customerId": customer_id,
        })
        # Workaround for SDK bug: ServiceEdgeControllerAPI.list_service_edges
        # references self._zpa but __init__ only sets self._zpa_base_endpoint.
        se = self._sdk.zpa.service_edges
        if not hasattr(se, "_zpa") and hasattr(se, "_zpa_base_endpoint"):
            se._zpa = se._zpa_base_endpoint

    # ------------------------------------------------------------------
    # Certificates
    # ------------------------------------------------------------------

    def list_certificates(self, page: int = 1, page_size: int = 500) -> List[Dict]:
        result, resp, err = self._sdk.zpa.certificates.list_certificates({"page_size": page_size})
        return _to_dicts(_unwrap(result, resp, err))

    def list_issued_certificates(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.certificates.list_issued_certificates()
        return _to_dicts(_unwrap(result, resp, err))

    def get_certificate(self, cert_id: str) -> Optional[Dict]:
        try:
            result, resp, err = self._sdk.zpa.certificates.get_certificate(cert_id)
            return _to_dict(_unwrap(result, resp, err))
        except Exception:
            return None

    def upload_certificate(self, name: str, cert_blob: str, description: str = "") -> Dict:
        result, resp, err = self._sdk.zpa.certificates.add_certificate(
            name=name, pem=cert_blob, description=description
        )
        return _to_dict(_unwrap(result, resp, err))

    def delete_certificate(self, cert_id: str) -> bool:
        result, resp, err = self._sdk.zpa.certificates.delete_certificate(cert_id)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Application Segments
    # ------------------------------------------------------------------

    def list_applications(self, app_type: str = "BROWSER_ACCESS") -> List[Dict]:
        result, resp, err = self._sdk.zpa.application_segment.list_segments()
        return _to_dicts(_unwrap(result, resp, err))

    def get_application(self, app_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.application_segment.get_segment(app_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_application(self, app_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.application_segment.update_segment(app_id, **config)
        _unwrap(result, resp, err)
        return True

    def create_application(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zpa.application_segment.add_segment(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def enable_application(self, app_id: str) -> bool:
        config = self.get_application(app_id)
        config["enabled"] = True
        # The GET response contains both tcp_port_range and tcp_port_ranges;
        # passing both to the SDK raises a conflict error — strip the plural forms.
        config.pop("tcp_port_ranges", None)
        config.pop("udp_port_ranges", None)
        return self.update_application(app_id, config)

    def disable_application(self, app_id: str) -> bool:
        config = self.get_application(app_id)
        config["enabled"] = False
        config.pop("tcp_port_ranges", None)
        config.pop("udp_port_ranges", None)
        return self.update_application(app_id, config)

    # ------------------------------------------------------------------
    # PRA Portals
    # ------------------------------------------------------------------

    def list_pra_portals(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.pra_portal.list_portals()
        return _to_dicts(_unwrap(result, resp, err))

    def get_pra_portal(self, portal_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.pra_portal.get_portal(portal_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_pra_portal(self, portal_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.pra_portal.update_portal(portal_id, **config)
        _unwrap(result, resp, err)
        return True

    def create_pra_portal(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zpa.pra_portal.add_portal(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def delete_pra_portal(self, portal_id: str) -> bool:
        result, resp, err = self._sdk.zpa.pra_portal.delete_portal(portal_id)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Privileged Credentials
    # ------------------------------------------------------------------

    def list_credentials(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.pra_credential.list_credentials()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Segment Groups
    # ------------------------------------------------------------------

    def list_segment_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.segment_groups.list_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def create_segment_group(self, name: str, enabled: bool = True) -> Dict:
        result, resp, err = self._sdk.zpa.segment_groups.add_group(name=name, enabled=enabled)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Server Groups
    # ------------------------------------------------------------------

    def list_server_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.server_groups.list_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def create_server_group(self, name: str, enabled: bool = True) -> Dict:
        result, resp, err = self._sdk.zpa.server_groups.add_group(name=name, enabled=enabled)
        return _to_dict(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # App Connectors & Connector Groups
    # ------------------------------------------------------------------

    def list_connector_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.app_connector_groups.list_connector_groups()
        return _to_dicts(_unwrap(result, resp, err))

    def list_connectors(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.app_connectors.list_connectors()
        return _to_dicts(_unwrap(result, resp, err))

    # Connectors
    def get_connector(self, connector_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.app_connectors.get_connector(connector_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_connector(self, connector_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.app_connectors.update_connector(connector_id, **config)
        _unwrap(result, resp, err)
        return True

    def delete_connector(self, connector_id: str) -> bool:
        result, resp, err = self._sdk.zpa.app_connectors.delete_connector(connector_id)
        _unwrap(result, resp, err)
        return True

    # Connector Groups
    def get_connector_group(self, group_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.app_connector_groups.get_connector_group(group_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_connector_group(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zpa.app_connector_groups.add_connector_group(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def update_connector_group(self, group_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.app_connector_groups.update_connector_group(group_id, **config)
        _unwrap(result, resp, err)
        return True

    def delete_connector_group(self, group_id: str) -> bool:
        result, resp, err = self._sdk.zpa.app_connector_groups.delete_connector_group(group_id)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # IdP / SAML / SCIM
    # ------------------------------------------------------------------

    def list_idp(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.idp.list_idps()
        return _to_dicts(_unwrap(result, resp, err))

    def list_saml_attributes(self, idp_id: Optional[str] = None) -> List[Dict]:
        result, resp, err = self._sdk.zpa.saml_attributes.list_saml_attributes()
        return _to_dicts(_unwrap(result, resp, err))

    def list_scim_groups(self, idp_id: str) -> List[Dict]:
        result, resp, err = self._sdk.zpa.scim_groups.list_scim_groups(idp_id)
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Microtenants
    # ------------------------------------------------------------------

    def list_microtenants(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.microtenants.list_microtenants()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Enrollment Certificates
    # ------------------------------------------------------------------

    def list_enrollment_certificates(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.enrollment_certificates.list_enrolment()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Policy Sets
    # ------------------------------------------------------------------

    def list_policy_rules(self, policy_type: str) -> List[Dict]:
        result, resp, err = self._sdk.zpa.policies.list_rules(policy_type)
        return _to_dicts(_unwrap(result, resp, err))

    def get_policy_set(self, policy_type: str) -> Dict:
        result, resp, err = self._sdk.zpa.policies.get_policy(policy_type)
        return _to_dict(_unwrap(result, resp, err))

    def get_policy_rule(self, policy_type: str, rule_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.policies.get_rule(policy_type, rule_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_policy_rule(self, policy_type: str, rule_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.policies.update_rule(policy_type, rule_id, **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # PRA Consoles
    # ------------------------------------------------------------------

    def list_pra_consoles(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.pra_console.list_consoles()
        return _to_dicts(_unwrap(result, resp, err))

    def get_pra_console(self, console_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.pra_console.get_console(console_id)
        return _to_dict(_unwrap(result, resp, err))

    def create_pra_console(self, **kwargs) -> Dict:
        result, resp, err = self._sdk.zpa.pra_console.add_console(**kwargs)
        return _to_dict(_unwrap(result, resp, err))

    def update_pra_console(self, console_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.pra_console.update_console(console_id, **config)
        _unwrap(result, resp, err)
        return True

    def delete_pra_console(self, console_id: str) -> bool:
        result, resp, err = self._sdk.zpa.pra_console.delete_console(console_id)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Service Edge Groups
    # ------------------------------------------------------------------

    def list_service_edge_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.service_edge_group.list_service_edge_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Service Edges
    # ------------------------------------------------------------------

    def list_service_edges(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.service_edges.list_service_edges()
        return _to_dicts(_unwrap(result, resp, err))

    def get_service_edge(self, service_edge_id: str) -> Dict:
        result, resp, err = self._sdk.zpa.service_edges.get_service_edge(service_edge_id)
        return _to_dict(_unwrap(result, resp, err))

    def update_service_edge(self, service_edge_id: str, config: Dict) -> bool:
        result, resp, err = self._sdk.zpa.service_edges.update_service_edge(service_edge_id, **config)
        _unwrap(result, resp, err)
        return True

    # ------------------------------------------------------------------
    # Servers
    # ------------------------------------------------------------------

    def list_servers(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.servers.list_servers()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Machine Groups
    # ------------------------------------------------------------------

    def list_machine_groups(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.machine_groups.list_machine_groups()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # Trusted Networks
    # ------------------------------------------------------------------

    def list_trusted_networks(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.trusted_networks.list_trusted_networks()
        return _to_dicts(_unwrap(result, resp, err))

    # ------------------------------------------------------------------
    # LSS Configs
    # ------------------------------------------------------------------

    def list_lss_configs(self) -> List[Dict]:
        result, resp, err = self._sdk.zpa.lss.list_configs()
        return _to_dicts(_unwrap(result, resp, err))
