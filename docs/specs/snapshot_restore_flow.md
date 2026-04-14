# Spec: Dedicated Snapshot Restore Flow

**Status:** Draft  
**Date:** 2026-04-14  
**Author:** Architect (Claude Sonnet 4.6)

---

## 1. Summary and Motivation

The current `_restore_snapshot()` handler in `cli/menus/snapshots_menu.py` (lines 245-262) is a thin stub that delegates to `apply_baseline_menu()` in `zia_menu.py`. This makes the restore flow indistinguishable from a cross-tenant baseline migration: the operator is asked to choose between wipe-first and delta modes, and the delete list is presented as optional.

These are the wrong semantics for a snapshot restore. A restore is a rollback of the same tenant to a known prior state. The correct mental model is:

- The snapshot is the authoritative desired state.
- Everything in the tenant that is not in the snapshot must be deleted.
- The operator does not need a mode choice — wipe is always implied.
- A single confirmation covers the full operation (creates + updates + deletes).
- Post-delete verification confirms the deleted resources are actually gone.

**Apply Baseline is not changed.** Its wipe-first / delta choice and the optional delete confirmation remain exactly as they are today. This spec only concerns Restore Snapshot.

---

## 2. Flow Diagram

```
_restore_snapshot(tenant, client)
    |
    v
[Pick snapshot from list]
    |
    v
[Progress: Classify] ── ZIAPushService.classify_baseline(snap_resources)
    |                     (imports live state, computes creates/updates/skips)
    |    ── classify_snapshot_deletes(snap_resources) [NEW SERVICE METHOD]
    |                     (loads DB, finds resources in DB but not in snapshot)
    v
[Dry-run display] ── _render_restore_dry_run(dry_run, delete_candidates)
    |    Shows: CREATES | UPDATES | DELETES | SKIPS in one unified view
    |    Totals line: "X create(s), Y update(s), Z delete(s), W skip(s)"
    v
[Single confirm] ── "Apply restore of snapshot '<name>' to <tenant>?"
    |    If No → return
    v
[Execute creates + updates] ── ZIAPushService.push_classified(dry_run)
    |
    v
[Verify pass 1] ── ZIAPushService.verify_push(snap_resources)
    |    Discrepancies? → offer remediation (same pattern as apply_baseline_menu)
    v
[Execute deletes in WIPE_ORDER] ── ZIAPushService.execute_deletes(delete_candidates)
    |    Progress shown inline
    v
[Activate between wipe + push?] ── client.activate() silently after deletes
    |    (same as apply_baseline wipe-first: activate deletions before pushing
    |     to avoid stale-state ordering errors — but here push has already
    |     happened, so this activation is for the deletes only)
    v
[Verify pass 2] ── ZIAPushService.verify_deleted(delete_candidates) [NEW]
    |    Confirms deleted resource IDs are no longer present in live tenant
    v
[Activate] ── offer final ZIA activation; route through _zia_changed()
    |
    v
[Write restore log] ── _write_restore_log(snap, tenant, dry_run,
                            push_records, delete_records, verify1, verify2)
    v
[press_any_key_to_continue]
```

**Revised sequence note:** Because `push_classified()` must run before `execute_deletes()`, the activation ordering mirrors the wipe-first path: the delete activation fires after push and before the final state check. In practice this means:

1. Creates/updates pushed → verify pass 1 (checks creates/updates landed).
2. Deletes executed → `client.activate()` silently (same as apply_baseline wipe-first comment "Activate deletions before push" — except here we say "Activate deletions after push").
3. Verify pass 2 (confirms deleted IDs are gone).
4. Offer final activation to the operator (covers any remaining pending state).

---

## 3. Design Question Resolutions

### 3.1 Where does delete classification live?

**Decision: add `classify_snapshot_deletes()` as a new method on `ZIAPushService`.**

Rationale:
- The logic requires access to `_load_existing_from_db()` and the `_is_zscaler_managed()` / `SKIP_NAMED` guards — all of which are private to the service class.
- Doing it inline in the menu handler would require duplicating these guards or making them module-level, which violates the service-layer boundary.
- Extending `classify_baseline()` to return deletes would conflate two operations: classify_baseline is called on both cross-tenant and same-tenant flows; the delete semantics differ between them. Keeping it separate preserves clarity.

Signature:

```python
def classify_snapshot_deletes(
    self,
    snapshot_resources: Dict[str, List[dict]],
) -> List[PushRecord]:
    """Identify resources present in the DB that are absent from the snapshot.

    Does NOT run an import — the caller is expected to have already run
    classify_baseline() (which imports live state) immediately before calling
    this method, so the DB reflects current tenant state.

    Returns a list of PushRecord with status="pending_delete:<zia_id>",
    sorted in WIPE_ORDER so execute_deletes() can consume it directly.

    Args:
        snapshot_resources: The "resources" dict from a RestorePoint snapshot,
            shape: {resource_type: [{"id": ..., "name": ..., "raw_config": {...}}, ...]}
    """
```

Implementation:
- Load `existing = self._load_existing_from_db()` (DB already reflects the post-import state from the preceding `classify_baseline()` call).
- Build a set of IDs present in the snapshot per resource type: `snap_ids[rtype] = {entry["id"] for entry in snapshot_resources.get(rtype, [])}`.
- Iterate `WIPE_ORDER`. For each `rtype`:
  - Skip if `rtype in SKIP_TYPES` or `rtype not in _DELETE_METHODS`.
  - Skip `allowlist` / `denylist` (no individual deletion path).
  - For each `(zia_id, entry)` in `existing.get(rtype, {}).items()`:
    - Skip if `_is_zscaler_managed(rtype, entry["raw_config"])`.
    - Skip if `entry["name"] in SKIP_NAMED.get(rtype, set())`.
    - Skip if `zia_id in snap_ids.get(rtype, set())` — resource is in the snapshot, not a delete candidate.
    - Append `PushRecord(resource_type=rtype, name=entry["name"] or zia_id, status=f"pending_delete:{zia_id}")`.
- Return the list (already in WIPE_ORDER from the outer loop).

### 3.2 What does the unified dry-run display look like?

**Decision: new helper `_render_restore_dry_run()` in `snapshots_menu.py`, not reusing `_render_dry_run_table()` from `zia_menu.py`.**

Rationale:
- `apply_baseline_menu()` does not have a standalone `_render_dry_run_table()` helper; the dry-run rendering is inline in the function body. There is nothing to reuse.
- Calling into `zia_menu.py` from `snapshots_menu.py` would tighten the circular-import risk (see constraint 3.4).
- The restore display is simpler: no mode narrative, no "skipped in delta mode" copy, no baseline file contents table.

`_render_restore_dry_run(dry_run: DryRunResult, delete_candidates: List[PushRecord])` prints:

```
Restore Dry Run — snapshot: '<snap.name>'

Resource Type     Create  Update  Delete  Skip
─────────────────────────────────────────────
firewall_rule        2       1       3      0
url_category         0       0       1      0
...

To create (N):
  firewall_rule: My Corp Rule
  ...

To update (N):
  ...

To delete (N):
  firewall_rule: Old Rule
  ...  (capped at _MAX_DETAIL = 30 each, with "... and X more")

Total: X create(s), Y update(s), Z delete(s), W skip(s)
```

The summary table includes a Delete column populated from `delete_candidates` (not from `dry_run.to_delete`, which comes from `classify_baseline()` and reflects the cross-tenant delete logic). See data contract in section 5.

### 3.3 Where does the new restore flow live?

**Decision: `restore_snapshot_menu()` function added to `snapshots_menu.py`.**

Rationale:
- The entry point is already in `snapshots_menu.py` (`_restore_snapshot`). Moving logic to a new file would require an extra import and provide no architectural benefit at this scale.
- A free function `restore_snapshot_menu(tenant, client)` keeps the pattern consistent with the existing handlers in the file.

`_restore_snapshot()` becomes:

```python
def _restore_snapshot(tenant, client) -> None:
    snap = _pick_snapshot(tenant, "ZIA")
    if snap is None:
        return
    restore_snapshot_menu(tenant, client, snap)
```

`restore_snapshot_menu(tenant, client, snap)` is the new function that contains the entire flow.

### 3.4 Circular import

`zia_menu.py` already imports `snapshots_menu` at module level (line 7: `from cli.menus.snapshots_menu import snapshots_menu`). The new `restore_snapshot_menu()` in `snapshots_menu.py` needs `ZIAPushService` and `_zia_changed`. Both must be deferred imports inside the function body — exactly the same pattern used by the existing `_restore_snapshot()` stub for `apply_baseline_menu`.

```python
def restore_snapshot_menu(tenant, client, snap) -> None:
    # Deferred imports — zia_menu imports snapshots_menu at module level.
    from cli.menus.zia_menu import _zia_changed
    from services.zia_push_service import ZIAPushService
    ...
```

### 3.5 Post-delete verify: what exactly does it check?

**Decision: add `verify_deleted()` as a new method on `ZIAPushService`.**

`verify_push()` re-runs `classify_baseline()` against the baseline — this checks whether creates/updates landed, but it does not check whether deletes are gone (because deleted IDs are simply absent from the pending queue, not positively confirmed absent from the live tenant).

`verify_deleted(delete_candidates)` performs a targeted check:
- Groups the `delete_candidates` by `resource_type`.
- For each type, calls the appropriate list method on the client to fetch current live resources (or uses the already-imported DB state from a fresh import).
- Reports any `zia_id` from `delete_candidates` that is still present in the live result.

Signature:

```python
def verify_deleted(
    self,
    delete_candidates: List[PushRecord],
    import_progress_callback: Optional[Callable] = None,
) -> List[PushRecord]:
    """Confirm that resources from delete_candidates are no longer present.

    Runs a fresh import of the relevant resource types, then returns a list
    of PushRecord entries (from delete_candidates) whose zia_id still appears
    in the live tenant.  An empty return list means all deletes confirmed.

    Args:
        delete_candidates: The list returned by classify_snapshot_deletes()
            and consumed by execute_deletes() — used to extract zia_ids to check.
        import_progress_callback: Optional progress callback.
    """
```

Implementation:
- Extract the set of `(rtype, zia_id)` pairs from `delete_candidates` (parsing `zia_id` from `status` or accepting it from a PushRecord attribute).
- Run `ZIAImportService.run(resource_types=list(rtypes_to_check))` for a targeted re-import.
- Call `self._load_existing_from_db()` and check which zia_ids are still present.
- Return PushRecords for the still-present ones with `status="failed:still_present"`.

Note: if the delete_candidates list is empty (no deletes required), `verify_deleted` is a no-op and returns `[]`.

---

## 4. Service Layer Changes

### 4.1 New method: `ZIAPushService.classify_snapshot_deletes()`

File: `services/zia_push_service.py`

- No new imports required.
- Uses existing `_load_existing_from_db()`, `WIPE_ORDER`, `SKIP_TYPES`, `_DELETE_METHODS`, `_is_zscaler_managed()`, `SKIP_NAMED`.
- Returns `List[PushRecord]` with `status="pending_delete:<zia_id>"`.
- Does not run an import — relies on the DB state left by the immediately preceding `classify_baseline()` call.

### 4.2 New method: `ZIAPushService.verify_deleted()`

File: `services/zia_push_service.py`

- Uses `ZIAImportService` (already imported via deferred import in other methods).
- Uses `_load_existing_from_db()`.
- Returns `List[PushRecord]` — entries still present in the live tenant after deletion.

### 4.3 No changes to existing methods

`classify_baseline()`, `push_classified()`, `verify_push()`, `execute_deletes()`, `WIPE_ORDER`, `PUSH_ORDER`, `DryRunResult`, `PushRecord`, `WipeResult`, `WipeRecord` are unchanged.

---

## 5. UI Layer Changes

### 5.1 `cli/menus/snapshots_menu.py`

**New function: `restore_snapshot_menu(tenant, client, snap) -> None`**

Full algorithm:

```
1. render_banner()
2. Print header: "Restore Snapshot — <snap.name>"
3. Print snapshot metadata (name, created_at, resource_count, comment).

4. service = ZIAPushService(client, tenant_id=tenant.id)  [deferred import]

5. with console.status("Classifying..."):
       dry_run = service.classify_baseline({"product": "ZIA", "resources": snap.snapshot["resources"]},
                                           import_progress_callback=_progress)
       delete_candidates = service.classify_snapshot_deletes(snap.snapshot["resources"])

6. _render_restore_dry_run(dry_run, delete_candidates)
   [prints unified table + per-action detail lists]

7. If everything is empty (zero creates, updates, deletes, non-trivial skips):
       print "Nothing to restore — tenant already matches this snapshot."
       press_any_key_to_continue(); return

8. confirmed = questionary.confirm(
       "Apply restore of snapshot '<snap.name>' to <tenant.name>?", default=False
   )
   if not confirmed: return

9. push_records = []
   if dry_run.create_count > 0 or dry_run.update_count > 0:
       with console.status("Pushing creates and updates..."):
           push_records = service.push_classified(dry_run, progress_callback=_push_progress)
       print summary counts (created / updated / failed)

10. verify1_result = None
    if push_records:
        with console.status("Verifying creates and updates..."):
            verify1_result = service.verify_push(
                {"product": "ZIA", "resources": snap.snapshot["resources"]},
                import_progress_callback=_progress
            )
        if verify1_result has discrepancies:
            show discrepancy table
            offer remediation → service.push_classified(verify1_result)

11. delete_records = []
    if delete_candidates:
        with console.status("Deleting resources absent from snapshot..."):
            delete_records = service.execute_deletes(delete_candidates, progress_callback=_del_progress)
        deleted_count = sum(1 for r in delete_records if r.is_deleted)
        del_failed_count = sum(1 for r in delete_records if r.is_failed)
        print "Deleted: N  Failed: M"

        if deleted_count > 0:
            # Activate deletions (mirrors apply_baseline wipe-first pattern)
            try:
                client.activate()
            except Exception as e:
                print warning but continue

12. verify2_result = []
    if delete_candidates:
        with console.status("Verifying deletions..."):
            verify2_result = service.verify_deleted(delete_candidates)
        if verify2_result:
            print warning table: "N resource(s) still present after delete"
        else:
            print "Deletions confirmed."

13. _zia_changed()  [deferred import from zia_menu]
    [marks pending + prints reminder]

14. _write_restore_log(snap, tenant, dry_run, delete_candidates,
                        push_records, delete_records, verify1_result, verify2_result)

15. Offer activation:
    activate_now = questionary.confirm("Activate changes in ZIA now?", default=True)
    if activate_now:
        client.activate()
        [print status]

16. press_any_key_to_continue()
```

**Modified function: `_restore_snapshot(tenant, client) -> None`**

Becomes a two-line wrapper:

```python
def _restore_snapshot(tenant, client) -> None:
    snap = _pick_snapshot(tenant, "ZIA")
    if snap is None:
        return
    restore_snapshot_menu(tenant, client, snap)
```

**New helper: `_render_restore_dry_run(dry_run, delete_candidates)`**

Private to `snapshots_menu.py`. Builds and prints:
- Summary table: Resource Type | Create | Update | Delete | Skip (where Delete column comes from `delete_candidates`, not `dry_run.to_delete`).
- Per-action detail lists (capped at `_MAX_DETAIL = 30`).
- Total line.

**New helper: `_write_restore_log(snap, tenant, dry_run, delete_candidates, push_records, delete_records, verify1, verify2)`**

Mirrors `_write_push_log()` from `zia_menu.py`. Writes to `~/.local/share/zs-config/logs/zia-restore-<timestamp>.log`. Returns log path or None. Logs: snapshot name/ID, tenant name/ID, dry-run classification counts, full per-record push results, delete results, verify 1 discrepancies, verify 2 still-present list.

### 5.2 No changes to `cli/menus/zia_menu.py`

`apply_baseline_menu()`, `_zia_changed()`, `_write_push_log()` are all unchanged.

---

## 6. Data Contracts

### 6.1 `classify_snapshot_deletes()` return value

`List[PushRecord]` where each entry has:
- `resource_type`: one of the types in `WIPE_ORDER` (only deletable types are included)
- `name`: resource name from the DB entry, or `zia_id` as fallback
- `status`: `"pending_delete:<zia_id>"` — same encoding used by `classify_baseline()` for its `to_delete` list, making it directly consumable by `execute_deletes()`
- `warnings`: `[]` (none at classification time)

The list is returned in `WIPE_ORDER` sequence (rules before objects, reverse-dependency). `execute_deletes()` re-sorts by `WIPE_ORDER` internally anyway, so this is belt-and-suspenders.

### 6.2 `verify_deleted()` return value

`List[PushRecord]` of resources that are **still present** in the live tenant after deletion:
- `resource_type`, `name`: from the original delete candidate
- `status`: `"failed:still_present"`
- `warnings`: `[]`

An empty list is the success case.

### 6.3 Snapshot `resources` dict shape

Already defined by `snapshot_service.get_snapshot_data_current()`:

```python
{
  "resource_type": [
    {"id": "<zia_id>", "name": "<name>", "raw_config": {...}},
    ...
  ],
  ...
}
```

`classify_snapshot_deletes()` receives this dict directly from `snap.snapshot["resources"]`. ID comparison uses the `"id"` field, which matches `ZIAResource.zia_id` in the DB.

### 6.4 Baseline dict passed to `classify_baseline()` and `verify_push()`

```python
{"product": "ZIA", "resources": snap.snapshot["resources"]}
```

This is the same envelope used by the existing `_restore_snapshot()` stub and by the JSON file path in `apply_baseline_menu()`.

---

## 7. Edge Cases

### 7.1 Empty diff (tenant already matches snapshot)

After step 5, if `dry_run.create_count == 0` and `dry_run.update_count == 0` and `len(delete_candidates) == 0`:
- Print: "Nothing to restore — tenant already matches this snapshot."
- `press_any_key_to_continue()` and return without any mutations or activation.

### 7.2 All-delete (snapshot is empty or all resources were added after snapshot)

- `dry_run.pending` is empty; `dry_run.create_count == 0` and `dry_run.update_count == 0`.
- `delete_candidates` may be large.
- Steps 9 and 10 are skipped (no push_classified, no verify pass 1).
- Proceed directly to step 11 (execute deletes) and step 12 (verify deleted).
- `_zia_changed()` is still called; activation is still offered.

### 7.3 Partial failure during creates/updates (step 9)

- Some `push_records` have `is_failed == True`.
- Verify pass 1 will surface the un-applied resources as discrepancies.
- If the operator declines remediation, proceed to deletes anyway — the restore is partial but we continue, and the log records the full state.
- Do not abort the delete step on push failure alone; the operator confirmed the full restore and should be able to proceed.

### 7.4 Partial failure during deletes (step 11)

- Some `delete_records` have `is_failed == True`.
- `verify_deleted()` will confirm the still-present IDs (step 12).
- The still-present list is printed as a warning table, not a fatal error.
- Activation is still offered; activation of what did succeed is better than leaving everything pending.

### 7.5 Verification import failure

- If `verify_push()` or `verify_deleted()` raises an exception, print a yellow warning and continue to the activation step. Mirrors the `apply_baseline_menu()` try/except around `verify_push()`.

### 7.6 Ctrl+C / questionary returns None at confirmation

- `questionary.confirm(...).ask()` returns `None` on Ctrl+C.
- Guard: `if not confirmed: return` handles both `False` and `None`.

### 7.7 `allowlist` / `denylist` in delete candidates

- `classify_snapshot_deletes()` skips `allowlist` and `denylist` (same as `classify_wipe()`).
- These are singletons with merge semantics; there is no per-item deletion path.
- If a restore needs to reset the allowlist/denylist to the snapshot state, that is handled by `push_classified()` (which updates the singleton), not by `execute_deletes()`.

### 7.8 Singletons (`advanced_settings`, `url_filter_cloud_app_settings`, `browser_control_settings`)

- These are not in `_DELETE_METHODS` and will never appear in `delete_candidates`.
- `classify_baseline()` will queue them as updates if their config differs.
- `push_classified()` handles them via the singleton update path.

### 7.9 SQLite write-lock

- `classify_baseline()` internally calls `ZIAImportService.run()`, which opens and closes its own session. It collects audit events in a list and writes them after the session closes — the existing import service already follows this rule.
- `restore_snapshot_menu()` must not wrap any of the service calls in a `with get_session()` block.
- `audit_service.log()` calls (if any are added for the restore operation itself) must be made after all service calls return, never inside a service call.

---

## 8. Out of Scope

- **Apply Baseline is unchanged.** `apply_baseline_menu()` in `zia_menu.py`, its wipe-first/delta mode choice, the optional delete confirmation, and `_write_push_log()` are not modified.
- **ZPA snapshot restore.** The `Restore Snapshot` menu option is currently ZIA-only (gated by `product == "ZIA"` in `snapshots_menu()`). ZPA push service is a separate system; this spec does not address ZPA restore.
- **Undo / re-snapshot before restore.** The spec does not auto-save a snapshot before restoring. If the operator wants a safety net, they should manually save a snapshot before running the restore.
- **Selective restore.** This flow restores all resource types. Per-type or per-resource selection is not in scope.
- **Dry-run-only mode.** There is no "preview only, do not apply" option — the dry-run display before the single confirmation serves this purpose.
- **`tenancy_restriction_profile`, `location`** in delete candidates. These types appear in `_DELETE_METHODS` but are env-specific. If a restore snapshot captured them, `classify_snapshot_deletes()` will include them like any other non-Zscaler-managed resource. This matches the wipe-first behavior in `apply_baseline_menu()` and is intentional — the operator should be aware of what is being deleted.

---

## 9. Files Affected

| File | Change |
|---|---|
| `services/zia_push_service.py` | Add `classify_snapshot_deletes()` and `verify_deleted()` methods to `ZIAPushService` |
| `cli/menus/snapshots_menu.py` | Add `restore_snapshot_menu()`, `_render_restore_dry_run()`, `_write_restore_log()`; simplify `_restore_snapshot()` to a wrapper |
| `cli/menus/zia_menu.py` | No changes |
| `services/snapshot_service.py` | No changes |
| `db/models.py` | No changes |
