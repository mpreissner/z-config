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

def create_task(
    name: str,
    source_tenant_id: int,
    target_tenant_id: int,
    resource_groups: List[str],
    schedule: str,
    sync_deletes: bool = False,
    enabled: bool = True,
    owner_email: Optional[str] = None,
    sync_mode: str = "resource_type",
    label_name: Optional[str] = None,
    label_resource_types: Optional[List[str]] = None,
) -> ScheduledTask:
    """Create a new scheduled task and register it with the scheduler.

    Raises ValueError for validation errors.
    """
    if source_tenant_id == target_tenant_id:
        raise ValueError("source_tenant_id and target_tenant_id must differ.")

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
        # resource_groups may be [] in label mode; store as empty list
        resource_groups = resource_groups or []

    cron_expression = resolve_schedule(schedule)

    with get_session() as session:
        task = ScheduledTask(
            name=name,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            resource_groups=resource_groups,
            cron_expression=cron_expression,
            sync_deletes=sync_deletes,
            enabled=enabled,
            owner_email=owner_email or None,
            sync_mode=sync_mode,
            label_name=label_name.strip() if label_name else None,
            label_resource_types=label_resource_types or None,
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
    target_tenant_id: Optional[int] = None,
    resource_groups: Optional[List[str]] = None,
    schedule: Optional[str] = None,
    sync_deletes: Optional[bool] = None,
    enabled: Optional[bool] = None,
    owner_email: Optional[str] = None,
    sync_mode: Optional[str] = None,
    label_name: Optional[str] = None,
    label_resource_types: Optional[List[str]] = None,
) -> Optional[ScheduledTask]:
    """Update an existing task. Only provided (non-None) fields are changed.

    Returns the updated task, or None if not found.
    Raises ValueError for validation errors.
    """
    with get_session() as session:
        task = session.get(ScheduledTask, task_id)
        if task is None:
            return None

        new_source = source_tenant_id if source_tenant_id is not None else task.source_tenant_id
        new_target = target_tenant_id if target_tenant_id is not None else task.target_tenant_id
        if new_source == new_target:
            raise ValueError("source_tenant_id and target_tenant_id must differ.")

        effective_mode = sync_mode if sync_mode is not None else task.sync_mode

        if sync_mode is not None:
            if sync_mode not in ("resource_type", "label"):
                raise ValueError("sync_mode must be 'resource_type' or 'label'.")

        switching_to_resource_type = sync_mode == "resource_type" and task.sync_mode == "label"
        switching_to_label = sync_mode == "label" and task.sync_mode == "resource_type"

        if effective_mode == "resource_type":
            if switching_to_resource_type and resource_groups is None:
                raise ValueError(
                    "resource_groups is required when switching sync_mode to 'resource_type'."
                )
            if resource_groups is not None:
                if not resource_groups:
                    raise ValueError("resource_groups must be a non-empty list.")
                for g in resource_groups:
                    if g not in RESOURCE_GROUP_MAP:
                        raise ValueError(f"Unknown resource group: '{g}'")
                task.resource_groups = resource_groups
            if switching_to_resource_type:
                task.label_name = None
                task.label_resource_types = None
        elif effective_mode == "label":
            if switching_to_label:
                task.resource_groups = []
            elif resource_groups is not None:
                task.resource_groups = []
            if label_name is not None:
                if not label_name.strip():
                    raise ValueError("label_name cannot be empty when sync_mode is 'label'.")
                task.label_name = label_name.strip()
            if label_resource_types is not None:
                for rtype in label_resource_types:
                    if rtype not in LABEL_SUPPORTED_RESOURCE_TYPES:
                        raise ValueError(f"Unsupported label resource type: '{rtype}'")
                task.label_resource_types = label_resource_types or None

        if sync_mode is not None:
            task.sync_mode = sync_mode

        if name is not None:
            task.name = name
        if source_tenant_id is not None:
            task.source_tenant_id = source_tenant_id
        if target_tenant_id is not None:
            task.target_tenant_id = target_tenant_id
        if schedule is not None:
            task.cron_expression = resolve_schedule(schedule)
        if sync_deletes is not None:
            task.sync_deletes = sync_deletes
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
    from db.database import get_db_url

    db_url = get_db_url()
    jobstores = {
        "default": SQLAlchemyJobStore(url=db_url),
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
    from services.scheduled_sync_engine import run_sync_task

    jid = _job_id(task.id)
    trigger = CronTrigger.from_crontab(task.cron_expression)

    if _scheduler.get_job(jid):
        _scheduler.reschedule_job(jid, trigger=trigger)
    else:
        _scheduler.add_job(
            run_sync_task,
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
    )
    return copy
