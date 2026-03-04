#!/usr/bin/env python3
"""zs-config — interactive TUI for Zscaler OneAPI.

Installed usage:  zs-config
Development:      pip install -e .  then  zs-config
"""


def main():
    from db.database import init_db
    from cli.banner import render_banner
    from cli.menus import select_tenant
    from cli.menus.main_menu import main_menu
    from cli.session import set_active_tenant
    from cli.update_checker import check_for_updates

    init_db()
    render_banner()
    check_for_updates()

    # Select active tenant at startup (skipped if none are configured yet)
    from services.config_service import list_tenants
    if list_tenants():
        tenant = select_tenant()
        if tenant:
            set_active_tenant(tenant)

    main_menu()


if __name__ == "__main__":
    main()
