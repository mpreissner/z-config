# Contributing to zs-config

Thanks for your interest in contributing.

## Getting Started

1. Fork the repository and create a branch from `dev` (not `main`)
2. Install dependencies: `pip install -r requirements.txt`
3. Launch the TUI: `python cli/z_config.py`
4. Make your changes, keeping the existing code style
5. Test manually against a real or sandbox Zscaler tenant where possible
6. Submit a pull request against `dev`

## Branch Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable releases only |
| `dev` | Active development — all PRs target here |

## What to Work On

Check the [issues](../../issues) for open bugs and feature requests. If you want to add something new, open an issue first so we can discuss the approach before you invest time in it.

---

## TUI Patterns

- Services are pure business logic with no CLI concerns; menus handle only display and input
- All writes to the Zscaler API must be logged via `audit_service.log()`
- Table views should use `scroll_view(render_rich_to_lines(table), header_ansi=capture_banner())` from `cli/scroll_view.py`
- questionary prompts use plain text only — no Rich markup tags in choice labels or prompt strings
- ZIA mutations must route through `_zia_changed()` in `zia_menu.py` to set the pending-activation flag

---

## Web UI Patterns

### Tech stack

- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Query (`@tanstack/react-query`)
- **Backend**: FastAPI, SQLAlchemy, python-jose (JWT)
- **Dev venv**: `~/zscaler-env/`

### Local development

```bash
# Backend (from repo root)
source ~/zscaler-env/bin/activate
uvicorn api.main:app --reload

# Frontend (from web/)
npm install
npm run dev        # Vite dev server — proxies /api to the FastAPI server
npm run build      # Build to ../api/static/ for the container
```

### Docker development

```bash
docker compose down
docker compose up -d --build
```

Always run `down` before `up -d --build` — starting a new container without stopping the old one can leave orphaned processes holding the DB lock.

### Accordion / SectionGroup pattern (TenantWorkspacePage)

All read content in `TenantWorkspacePage` uses a two-level collapsible structure:

```tsx
<SectionGroup title="Network Security" isOpen={...} onToggle={...}>
  <Accordion title="Firewall Policy" isOpen={...} onToggle={...}>
    <FirewallRulesSection tenantName={tenant.name} isOpen={...} />
  </Accordion>
</SectionGroup>
```

- Each section is a standalone function component (`function FirewallRulesSection(...)`)
- Data fetching happens inside the section component, gated on `isOpen` so queries only fire when the accordion is open
- `useQuery` with `enabled: isOpen` is the standard pattern

### DB-first reads

All read sections fetch from the local DB (via the FastAPI `/api/v1/zia/...` endpoints backed by `ZIAResource` rows) rather than the live Zscaler API. The **Import** button in the top toolbar triggers a fresh pull from the API and updates the DB. This ensures the UI is fast and works without live API access for read operations.

### API client pattern

Each product area has a typed fetch module in `web/src/api/`:

```typescript
export async function fetchFirewallRules(tenantName: string): Promise<FirewallRule[]> {
  return apiFetch<FirewallRule[]>(`/api/v1/zia/${tenantName}/firewall_rules`);
}
```

All API calls go through `apiFetch` in `web/src/api/client.ts`, which attaches the JWT and handles 401 responses.

### Before adding a write operation to the web UI

Check that the operation exists in `zia_menu.py` (or the relevant TUI menu) first. Client-side existence of an API method is not sufficient — the web UI is a quick-config companion to the TUI, not a replacement for it.

---

## Reporting Bugs

Use the [bug report template](../../issues/new?template=bug_report.md). Include:
- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS (for TUI), or browser and Docker version (for web UI)
- Zscaler product (ZPA / ZIA) and relevant configuration (sanitised)

## Feature Requests

Use the [feature request template](../../issues/new?template=feature_request.md).

## Security Issues

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md).
