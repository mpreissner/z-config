"""Shared helpers for CLI menus — tenant selection and client factory."""

from typing import Optional, Tuple

import questionary
from rich.console import Console

console = Console()


def select_tenant():
    """Prompt the user to select a tenant. Returns None if none are configured."""
    from services.config_service import list_tenants

    tenants = list_tenants()
    if not tenants:
        console.print(
            "[yellow]No tenants configured.[/yellow] "
            "Go to [bold]Settings → Manage Tenants → Add Tenant[/bold] first."
        )
        return None
    if len(tenants) == 1:
        return tenants[0]
    return questionary.select(
        "Select tenant:",
        choices=[questionary.Choice(t.name, value=t) for t in tenants],
    ).ask()


def get_zpa_client(tenant=None):
    """Return (ZPAClient, tenant) or (None, None) if setup is incomplete.

    Uses the session's active tenant when no tenant is explicitly supplied.
    """
    from cli.session import get_active_tenant
    from lib.auth import ZscalerAuth
    from lib.zpa_client import ZPAClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = get_active_tenant()
    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None
    if not tenant.zpa_customer_id:
        console.print(f"[red]Tenant '{tenant.name}' has no ZPA Customer ID configured.[/red]")
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZPAClient(auth, tenant.zpa_customer_id, tenant.oneapi_base_url), tenant


def get_zia_client(tenant=None):
    """Return (ZIAClient, tenant) or (None, None) if setup is incomplete.

    Uses the session's active tenant when no tenant is explicitly supplied.
    """
    from cli.session import get_active_tenant
    from lib.auth import ZscalerAuth
    from lib.zia_client import ZIAClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = get_active_tenant()
    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZIAClient(auth, tenant.oneapi_base_url), tenant


def get_zcc_client(tenant=None):
    """Return (ZCCClient, tenant) or (None, None) if setup is incomplete.

    Uses the session's active tenant when no tenant is explicitly supplied.
    """
    from cli.session import get_active_tenant
    from lib.auth import ZscalerAuth
    from lib.zcc_client import ZCCClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = get_active_tenant()
    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZCCClient(auth, tenant.oneapi_base_url), tenant


def get_zidentity_client(tenant=None):
    """Return (ZIdentityClient, tenant) or (None, None) if setup is incomplete.

    Uses the session's active tenant when no tenant is explicitly supplied.
    """
    from cli.session import get_active_tenant
    from lib.auth import ZscalerAuth
    from lib.zidentity_client import ZIdentityClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = get_active_tenant()
    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZIdentityClient(auth, tenant.oneapi_base_url), tenant


def get_zdx_client(tenant=None):
    """Return (ZDXClient, tenant) or (None, None) if setup is incomplete.

    Uses the session's active tenant when no tenant is explicitly supplied.
    """
    from cli.session import get_active_tenant
    from lib.auth import ZscalerAuth
    from lib.zdx_client import ZDXClient
    from services.config_service import decrypt_secret

    if tenant is None:
        tenant = get_active_tenant()
    if tenant is None:
        tenant = select_tenant()
    if tenant is None:
        return None, None

    auth = ZscalerAuth(tenant.zidentity_base_url, tenant.client_id, decrypt_secret(tenant.client_secret_enc))
    return ZDXClient(auth, tenant.oneapi_base_url), tenant
