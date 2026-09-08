"""Scheduled task CRUD and APScheduler lifecycle management.

Provides:
- RESOURCE_GROUP_MAP   — maps group keys to constituent resource_type strings
- expand_resource_groups() — deduplicated resource type list from group keys
- interval_to_cron()   — converts preset interval strings to cron expressions
- validate_cron()      — validates a cron expression via croniter
- CRUD functions       — create_task, get_task, list_tasks, update_task,
                         delete_task, enable_task, disable_task
- Scheduler lifecycle  — start_scheduler, stop_scheduler, reschedule_task,
                         remove_task_from_scheduler
"""

from datetime import datetime
from typing import Dict, List, Optional

from croniter import croniter

from db.database import get_session
from db.models import ScheduledTask, TaskRunHistory

# ---------------------------------------------------------------------------
# Resource group map
# ---------------------------------------------------------------------------

RESOURCE_GROUP_MAP: Dict[str, List[str]] = {
    "firewall": [
        "firewall_rule",
        "firewall_dns_rule",
        "firewall_ips_rule",
        "ip_source_group",
        "ip_destination_group",
        "network_service",
        "network_svc_group",
        "network_app_group",
    ],
    "ips": [
        "firewall_ips_rule",
    ],
    "dns_filter": [
        "firewall_dns_rule",
    ],
    "ssl_inspection": [
        "ssl_inspection_rule",
    ],
    "url_categories": [
        "url_category",
        "url_filter_cloud_app_settings",
    ],
    "url_filtering": [
        "url_filtering_rule",
    ],
    "cloud_app_control": [
        "cloud_app_control_rule",
        "cloud_app_instance",
    ],
    "dlp": [
        "dlp_engine",
        "dlp_dictionary",
        "dlp_web_rule",
    ],
    "network_objects": [
        "ip_source_group",
        "ip_destination_group",
        "network_service",
        "network_svc_group",
        "rule_label",
        "time_interval",
        "workload_group",
    ],
    "forwarding": [
        "forwarding_rule",
    ],
    "bandwidth": [
        "bandwidth_class",
        "bandwidth_control_rule",
    ],
    "nat": [
        "nat_control_rule",
    ],
    "sandbox": [
        "sandbox_rule",
    ],
    "tenancy": [
        "tenancy_restriction_profile",
    ],
}

# Singleton resource types excluded from sync — environment-specific or
# destructive to sync blindly cross-tenant.
_EXCLUDED_FROM_SYNC: set = {
    "advanced_settings",
    "browser_control_settings",
    "url_filter_cloud_app_settings",
    "allowlist",
    "denylist",
}

# Resource types that carry a 'labels' field and are therefore eligible for
# label-based sync mode.  Confirmed from _norm_* methods in zia_push_service.
LABEL_SUPPORTED_RESOURCE_TYPES: List[str] = [
    "firewall_rule",
    "url_filtering_rule",
    "ssl_inspection_rule",
    "forwarding_rule",
    "bandwidth_control_rule",
    "nat_control_rule",
    "dlp_web_rule",
    "firewall_dns_rule",
    "firewall_ips_rule",
    "sandbox_rule",
    "traffic_capture_rule",
    "cloud_app_control_rule",
]

# ---------------------------------------------------------------------------
# Interval presets → cron conversion
# ---------------------------------------------------------------------------

_INTERVAL_CRON: Dict[str, str] = {
    "1h":  "0 * * * *",
    "4h":  "0 */4 * * *",
    "12h": "0 */12 * * *",
    "24h": "0 0 * * *",
}


def interval_to_cron(interval: str) -> Optional[str]:
    """Convert a preset interval string to a cron expression.

    Returns None if the string is not a recognised preset (treat as raw cron).
    """
    return _INTERVAL_CRON.get(interval)


def validate_cron(expression: str) -> bool:
    """Return True if expression is a valid 5-field cron string."""
    try:
        croniter(expression)
        return True
    except (ValueError, KeyError):
        return False


def resolve_schedule(schedule: str) -> str:
    """Convert schedule input (interval preset or raw cron) to stored cron.

    Raises ValueError if the expression is not a valid interval preset or
    valid cron expression.
    """
    converted = interval_to_cron(schedule)
    if converted is not None:
        return converted
    if validate_cron(schedule):
        return schedule
    raise ValueError(
        f"Invalid schedule '{schedule}'. Use an interval preset (1h, 4h, 12h, 24h) "
        "or a valid 5-field cron expression."
    )


# ---------------------------------------------------------------------------
# Resource group expansion
# ---------------------------------------------------------------------------

def expand_resource_groups(groups: List[str]) -> List[str]:
    """Expand group keys to a deduplicated list of resource_type strings.

    Singleton types excluded from sync are filtered out of the result.
    Unknown group keys are silently ignored.
    """
    seen = set()
    result = []
    for group in groups:
        for rtype in RESOURCE_GROUP_MAP.get(group, []):
            if rtype not in seen and rtype not in _EXCLUDED_FROM_SYNC:
                seen.add(rtype)
                result.append(rtype)
    return result


# ---------------------------------------------------------------------------
# Scheduler singleton
# ---------------------------------------------------------------------------

_scheduler = None


def _get_scheduler():
    return _scheduler


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _validate_task_fields(
    task_type: str,
    name: str,
    source_tenant_id: int,
    target_tenant_id: Optional[int],
    target_tenant_ids: Optional[List[int]],
    resource_groups: Optional[List[str]],
    sync_deletes: bool,
    sync_mode: str,
    label_name: Optional[str],
    label_resource_types: Optional[List[str]],
    import_products: Optional[List[str]],
) -> tuple:
    """Validate task fields and return normalised (resource_groups, target_tenant_id, target_tenant_ids, import_products).

    Raises ValueError on any validation failure.
    """
    if task_type not in ("sync", "import"):
        raise ValueError("task_type must be 'sync' or 'import'.")
    if not name or not name.strip():
        raise ValueError("name must be non-empty.")

    if task_type == "sync":
        # import_products must be absent
        if import_products:
            raise ValueError("import_products must be absent for sync tasks.")

        has_single = target_tenant_id is not None
        has_multi = bool(target_tenant_ids)

        if not has_single and not has_multi:
            raise ValueError("Provide target_tenant_id (single) or target_tenant_ids (multi).")
        if has_single and has_multi:
            raise ValueError("Provide target_tenant_id or target_tenant_ids, not both.")

        if has_multi:
            # Deduplicate preserving order
            seen_ids = set()
            deduped = []
            for tid in target_tenant_ids:
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    deduped.append(tid)
            target_tenant_ids = deduped

            for tid in target_tenant_ids:
                if tid == source_tenant_id:
                    raise ValueError("target_tenant_ids must not contain source_tenant_id.")

            # Set target_tenant_id to first entry for FK integrity
            target_tenant_id = target_tenant_ids[0]
        else:
            # Single target
            if target_tenant_id == source_tenant_id:
                raise ValueError("source_tenant_id and target_tenant_id must differ.")
            target_tenant_ids = None

        if sync_mode not in ("resource_type", "label"):
            raise ValueError("sync_mode must be 'resource_type' or 'label'.")

        if sync_mode == "resource_type":
            if not resource_groups:
                raise ValueError("resource_groups must be a non-empty list.")
            for g in resource_groups:
                if g not in RESOURCE_GROUP_MAP:
                    raise ValueError(f"Unknown resource group: '{g}'")
        elif sync_mode == "label":
            if not label_name or not label_name.strip():
                raise ValueError("label_name is required when sync_mode is 'label'.")
            if label_resource_types is not None:
                for rtype in label_resource_types:
                    if rtype not in LABEL_SUPPORTED_RESOURCE_TYPES:
                        raise ValueError(f"Unsupported label resource type: '{rtype}'")
            resource_groups = resource_groups or []

        return resource_groups, target_tenant_id, target_tenant_ids, None

    else:  # task_type == "import"
        if target_tenant_id is not None:
            raise ValueError("target_tenant_id must be absent for import tasks.")
        if target_tenant_ids:
            raise ValueError("target_tenant_ids must be absent for import tasks.")
        if resource_groups:
            raise ValueError("resource_groups must be absent or empty for import tasks.")
        if sync_mode not in (None, "resource_type"):
            raise ValueError("sync_mode must be absent or 'resource_type' for import tasks.")
        if label_name:
            raise ValueError("label_name must be absent for import tasks.")
        if sync_deletes:
            raise ValueError("sync_deletes must be False for import tasks.")

        if not import_products:
            raise ValueError("import_products must be a non-empty list for import tasks.")

        valid_products = {"ZIA", "ZPA", "ZCC"}
        seen_products = set()
        deduped_products = []
        for p in import_products:
            if p not in valid_products:
                raise ValueError(f"Unknown product: '{p}'. Valid values: ZIA, ZPA, ZCC.")
            if p not in seen_products:
                seen_products.add(p)
                deduped_products.append(p)
        import_products = deduped_products

        return [], None, None, import_products


def create_task(
    name: str,
    source_tenant_id: int,
    schedule: str,
    task_type: str = "sync",
    target_tenant_id: Optional[int] = None,
    target_tenant_ids: Optional[List[int]] = None,
    resource_groups: Optional[List[str]] = None,
    sync_deletes: bool = False,
    enabled: bool = True,
    owner_email: Optional[str] = None,
    sync_mode: str = "resource_type",
    label_name: Optional[str] = None,
    label_resource_types: Optional[List[str]] = None,
    import_products: Optional[List[str]] = None,
) -> ScheduledTask:
    """Create a new scheduled task and register it with the scheduler.

    Raises ValueError for validation errors.
    """
    norm_groups, norm_target, norm_targets, norm_products = _validate_task_fields(
        task_type=task_type,
        name=name,
        source_tenant_id=source_tenant_id,
        target_tenant_id=target_tenant_id,
        target_tenant_ids=target_tenant_ids,
        resource_groups=resource_groups,
        sync_deletes=sync_deletes,
        sync_mode=sync_mode,
        label_name=label_name,
        label_resource_types=label_resource_types,
        import_products=import_products,
    )

    cron_expression = resolve_schedule(schedule)

    with get_session() as session:
        task = ScheduledTask(
            name=name,
            source_tenant_id=source_tenant_id,
            target_tenant_id=norm_target,
            resource_groups=norm_groups,
            cron_expression=cron_expression,
            sync_deletes=sync_deletes,
            enabled=enabled,
            owner_email=owner_email or None,
            sync_mode=sync_mode,
            label_name=label_name.strip() if label_name else None,
            label_resource_types=label_resource_types or None,
            task_type=task_type,
            target_tenant_ids=norm_targets,
            import_products=norm_products,
        )
        session.add(task)
        session.flush()
        session.refresh(task)
        # Detach from session before returning
        task_copy = _copy_task(task)

    if enabled and _scheduler is not None:
        _register_job(task_copy)

    return task_copy


def get_task(task_id: int) -> Optional[ScheduledTask]:
    """Return a detached ScheduledTask by ID, or None."""
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return None
        return _copy_task(task)


def list_tasks() -> List[ScheduledTask]:
    """Return all scheduled tasks ordered by name."""
    with get_session() as session:
        tasks = (
            session.query(ScheduledTask)
            .order_by(ScheduledTask.name)
            .all()
        )
        return [_copy_task(t) for t in tasks]


def update_task(
    task_id: int,
    name: Optional[str] = None,
    source_tenant_id: Optional[int] = None,
    task_type: Optional[str] = None,
    target_tenant_id: Optional[int] = None,
    target_tenant_ids: Optional[List[int]] = None,
    resource_groups: Optional[List[str]] = None,
    schedule: Optional[str] = None,
    sync_deletes: Optional[bool] = None,
    enabled: Optional[bool] = None,
    owner_email: Optional[str] = None,
    sync_mode: Optional[str] = None,
    label_name: Optional[str] = None,
    label_resource_types: Optional[List[str]] = None,
    import_products: Optional[List[str]] = None,
) -> Optional[ScheduledTask]:
    """Update an existing task. Only provided (non-None) fields are changed.

    Returns the updated task, or None if not found.
    Raises ValueError for validation errors.
    """
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return None

        # Compute effective merged values for full re-validation
        eff_task_type   = task_type if task_type is not None else (task.task_type or "sync")
        eff_name        = name if name is not None else task.name
        eff_source      = source_tenant_id if source_tenant_id is not None else task.source_tenant_id
        eff_target      = target_tenant_id if target_tenant_id is not None else task.target_tenant_id
        eff_targets     = target_tenant_ids if target_tenant_ids is not None else (
            list(task.target_tenant_ids) if task.target_tenant_ids else None
        )
        eff_groups      = resource_groups if resource_groups is not None else (
            list(task.resource_groups) if task.resource_groups else []
        )
        eff_sync_deletes = sync_deletes if sync_deletes is not None else task.sync_deletes
        eff_sync_mode   = sync_mode if sync_mode is not None else (task.sync_mode or "resource_type")
        eff_label_name  = label_name if label_name is not None else task.label_name
        eff_label_rtypes = label_resource_types if label_resource_types is not None else (
            list(task.label_resource_types) if task.label_resource_types else None
        )
        eff_products    = import_products if import_products is not None else (
            list(task.import_products) if task.import_products else None
        )

        # When switching from import → sync, clear any stale import products
        # and vice versa so validation doesn't trip on stale values.
        if eff_task_type == "sync" and import_products is None:
            eff_products = None
        if eff_task_type == "import" and target_tenant_id is None and target_tenant_ids is None:
            eff_target = None
            eff_targets = None

        norm_groups, norm_target, norm_targets, norm_products = _validate_task_fields(
            task_type=eff_task_type,
            name=eff_name,
            source_tenant_id=eff_source,
            target_tenant_id=eff_target,
            target_tenant_ids=eff_targets,
            resource_groups=eff_groups,
            sync_deletes=eff_sync_deletes,
            sync_mode=eff_sync_mode,
            label_name=eff_label_name,
            label_resource_types=eff_label_rtypes,
            import_products=eff_products,
        )

        # Apply all updates
        task.task_type = eff_task_type

        if name is not None:
            task.name = name
        if source_tenant_id is not None:
            task.source_tenant_id = source_tenant_id

        task.target_tenant_id = norm_target
        task.target_tenant_ids = norm_targets
        task.import_products = norm_products

        if eff_task_type == "sync":
            task.resource_groups = norm_groups
            task.sync_mode = eff_sync_mode
            if eff_sync_mode == "label":
                task.label_name = eff_label_name.strip() if eff_label_name else None
                task.label_resource_types = eff_label_rtypes or None
            else:
                task.label_name = None
                task.label_resource_types = None
            task.sync_deletes = eff_sync_deletes
        else:
            # import task — sync fields are not meaningful
            task.resource_groups = []
            task.sync_mode = "resource_type"
            task.label_name = None
            task.label_resource_types = None
            task.sync_deletes = False

        if schedule is not None:
            task.cron_expression = resolve_schedule(schedule)
        if enabled is not None:
            task.enabled = enabled
        if owner_email is not None:
            task.owner_email = owner_email or None

        task.updated_at = datetime.utcnow()
        session.flush()
        session.refresh(task)
        updated = _copy_task(task)

    # Reschedule in APScheduler
    if _scheduler is not None:
        if updated.enabled:
            _register_job(updated)
        else:
            _remove_job(task_id)

    return updated


def delete_task(task_id: int) -> bool:
    """Delete a task and its run history. Returns True if found and deleted."""
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return False
        session.delete(task)

    if _scheduler is not None:
        _remove_job(task_id)

    return True


def enable_task(task_id: int) -> Optional[ScheduledTask]:
    """Enable a task (sets enabled=True) and register it with the scheduler."""
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return None
        task.enabled = True
        task.updated_at = datetime.utcnow()
        session.flush()
        session.refresh(task)
        updated = _copy_task(task)

    if _scheduler is not None:
        _register_job(updated)

    return updated


def disable_task(task_id: int) -> Optional[ScheduledTask]:
    """Disable a task (sets enabled=False) and remove its APScheduler job."""
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return None
        task.enabled = False
        task.updated_at = datetime.utcnow()
        session.flush()
        session.refresh(task)
        updated = _copy_task(task)

    if _scheduler is not None:
        _remove_job(task_id)

    return updated


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    """Start the APScheduler BackgroundScheduler and reconcile jobs.

    Called once from the FastAPI lifespan after init_db().
    """
    global _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from db.database import get_engine

    jobstores = {
        "default": SQLAlchemyJobStore(engine=get_engine()),
    }
    _scheduler = BackgroundScheduler(jobstores=jobstores)
    _scheduler.start()

    _reconcile_jobs()


def stop_scheduler() -> None:
    """Shut down the APScheduler instance gracefully."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None


def reschedule_task(task_id: int) -> None:
    """Re-register an existing task's APScheduler job with its current cron."""
    task = get_task(task_id)
    if task is None:
        return
    if task.enabled and _scheduler is not None:
        _register_job(task)


def remove_task_from_scheduler(task_id: int) -> None:
    """Remove a task's APScheduler job if it exists."""
    if _scheduler is not None:
        _remove_job(task_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _job_id(task_id: int) -> str:
    return f"scheduled_task_{task_id}"


def _register_job(task: ScheduledTask) -> None:
    """Add or replace the APScheduler job for a task."""
    from apscheduler.triggers.cron import CronTrigger
    from services.scheduled_sync_engine import run_task

    jid = _job_id(task.id)
    trigger = CronTrigger.from_crontab(task.cron_expression)

    _scheduler.add_job(
        run_task,
        trigger=trigger,
        id=jid,
        args=[task.id],
        replace_existing=True,
        max_instances=1,
    )


def _remove_job(task_id: int) -> None:
    """Remove the APScheduler job for a task, if it exists."""
    jid = _job_id(task_id)
    if _scheduler is not None and _scheduler.get_job(jid):
        _scheduler.remove_job(jid)


def _reconcile_jobs() -> None:
    """On startup: ensure APScheduler jobs match the enabled tasks in DB.

    - For every enabled ScheduledTask row: ensure a job exists.
    - For every APScheduler job whose ID starts with 'scheduled_task_': remove
      it if the corresponding DB row is missing or disabled.
    """
    if _scheduler is None:
        return

    # Build set of task IDs that should have jobs
    with get_session() as session:
        enabled_tasks = (
            session.query(ScheduledTask)
            .filter_by(enabled=True)
            .all()
        )
        enabled_copies = [_copy_task(t) for t in enabled_tasks]

    enabled_ids = {t.id for t in enabled_copies}

    # Register missing jobs for enabled tasks
    for task in enabled_copies:
        jid = _job_id(task.id)
        if _scheduler.get_job(jid) is None:
            _register_job(task)

    # Remove orphan jobs (no corresponding enabled DB row)
    for job in _scheduler.get_jobs():
        if job.id.startswith("scheduled_task_"):
            try:
                tid = int(job.id[len("scheduled_task_"):])
            except ValueError:
                continue
            if tid not in enabled_ids:
                _scheduler.remove_job(job.id)


def _copy_task(task: ScheduledTask) -> ScheduledTask:
    """Return a detached copy of a ScheduledTask ORM instance.

    Avoids DetachedInstanceError after the session closes.
    """
    copy = ScheduledTask(
        id=task.id,
        name=task.name,
        source_tenant_id=task.source_tenant_id,
        target_tenant_id=task.target_tenant_id,
        resource_groups=list(task.resource_groups) if task.resource_groups else [],
        cron_expression=task.cron_expression,
        sync_deletes=task.sync_deletes,
        enabled=task.enabled,
        owner_email=task.owner_email,
        created_at=task.created_at,
        updated_at=task.updated_at,
        sync_mode=task.sync_mode,
        label_name=task.label_name,
        label_resource_types=list(task.label_resource_types) if task.label_resource_types else None,
        task_type=task.task_type or "sync",
        target_tenant_ids=list(task.target_tenant_ids) if task.target_tenant_ids else None,
        import_products=list(task.import_products) if task.import_products else None,
    )
    return copy
