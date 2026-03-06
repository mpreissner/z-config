"""Process-level session state for the CLI.

A single module-level variable holds the active tenant so every menu can
read it without passing it through every call stack.  Only the CLI should
write to this; lib/services must not depend on it.
"""

from typing import Optional

_active_tenant = None

# Tenant IDs with ZIA mutations that have not yet been activated
_zia_pending: set = set()


def mark_zia_pending(tenant_id: int) -> None:
    _zia_pending.add(tenant_id)


def clear_zia_pending(tenant_id: int) -> None:
    _zia_pending.discard(tenant_id)


def has_zia_pending(tenant_id: int) -> bool:
    return tenant_id in _zia_pending


def get_active_tenant():
    """Return the currently selected TenantConfig, or None."""
    return _active_tenant


def set_active_tenant(tenant) -> None:
    """Set the active tenant for this CLI session."""
    global _active_tenant
    _active_tenant = tenant


def clear_active_tenant() -> None:
    global _active_tenant
    _active_tenant = None
