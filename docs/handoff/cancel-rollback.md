# Handoff: Cancel Rollback for Snapshot Apply

## Context

The Stop button on snapshot apply (both Restore and Apply Snapshot from Other Tenant) currently marks
the job cancelled and stops the UI, but does NOT undo ZIA changes that were already pushed before
the user hit Stop. The cancelled-state warning message explicitly tells the user this.

## What needs to happen

When a job is cancelled mid-push, the backend should:

1. Detect the cancel signal between push iterations
2. Collect a list of all resources that were successfully created or updated before the cancel
3. Roll back those changes — delete created resources, restore updated resources to their pre-push
   state (requires capturing pre-push values during classify)

## Key files

- `api/jobs.py` — add `is_cancelled(job_id)` check; background threads should poll this between
  resource pushes and bail early
- `api/routers/tenants.py` — `apply_snapshot` and `preview_apply_snapshot` threads need to check
  `store.is_cancelled(job_id)` in progress callbacks and raise a sentinel exception to unwind
- `services/zia_push_service.py` — `push_classified` and `apply_baseline` need a stop-flag or
  callable that they check between records; on cancel, return partial results so the caller knows
  what to roll back
- `web/src/pages/TenantWorkspacePage.tsx` — update the cancelled-state message to say
  "Rolling back N changes…" and show a second progress stream, or just show a "rolled back N items"
  summary

## Design notes

- The pre-push state capture has to happen at classify time — `classify_baseline` already imports
  the current live state, so that data exists. It just isn't passed through to the apply phase today.
- Deletes (Wipe & Push pre-wipe phase) are harder to roll back — the resources are gone from ZIA.
  May be acceptable to skip rollback for the wipe phase and only roll back the push phase, with a
  clear message to the user.
- The rollback itself is just another push pass using the captured pre-classify live state as the
  target — same service methods, different data.
- Consider whether rollback failure (ZIA API errors during rollback) should be surfaced separately
  from the original cancel.

## Current behaviour to preserve

The cancelled warning message currently says:
> "Any changes already pushed to ZIA remain in effect and are not automatically rolled back."

This should be replaced with rollback progress once the feature is implemented.
