"""In-memory job store for background tasks that stream progress via SSE."""
import uuid
import threading
import time
from typing import Dict, Any, List, Optional, Tuple

# Finished jobs are retained this long so a client that reconnects late can
# still read the outcome, then pruned to keep the store from growing forever.
_FINISHED_TTL_SECONDS = 3600

_ACTIVE_STATUSES = ("running", "cancel_requested")


class _JobStore:
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, key: Optional[str] = None) -> str:
        """Register a new running job.

        ``key`` optionally identifies what the job operates on (e.g.
        ``"import:12:ZIA"``) so a client that lost the job_id can find the
        still-running job again via find_active().
        """
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._prune_locked()
            self._jobs[job_id] = {
                "status": "running",
                "events": [],
                "result": None,
                "error": None,
                "key": key,
                "started_at": time.time(),
                "finished_at": None,
            }
        return job_id

    def create_unique(self, key: str) -> Tuple[str, bool]:
        """Create a job for ``key`` unless one is already running.

        Returns ``(job_id, created)``. Atomic, so two simultaneous requests
        cannot both start work for the same key.
        """
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._prune_locked()
            existing = self._find_active_locked(key)
            if existing:
                return existing, False
            self._jobs[job_id] = {
                "status": "running",
                "events": [],
                "result": None,
                "error": None,
                "key": key,
                "started_at": time.time(),
                "finished_at": None,
            }
        return job_id, True

    def _prune_locked(self) -> None:
        """Drop finished jobs past their TTL. Caller must hold the lock."""
        cutoff = time.time() - _FINISHED_TTL_SECONDS
        stale = [
            jid for jid, job in self._jobs.items()
            if job["finished_at"] is not None and job["finished_at"] < cutoff
        ]
        for jid in stale:
            del self._jobs[jid]

    def _find_active_locked(self, key: str) -> Optional[str]:
        """Caller must hold the lock. Most recently started match wins."""
        matches = [
            (job["started_at"], jid)
            for jid, job in self._jobs.items()
            if job["key"] == key and job["status"] in _ACTIVE_STATUSES
        ]
        return max(matches)[1] if matches else None

    def find_active(self, key: str) -> Optional[str]:
        """Return the job_id of the running job for ``key``, if any."""
        with self._lock:
            return self._find_active_locked(key)

    def append(self, job_id: str, event: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["events"].append(event)

    def complete(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job["status"] in _ACTIVE_STATUSES:
                job["status"] = "done"
                job["result"] = result
                job["finished_at"] = time.time()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job["status"] in _ACTIVE_STATUSES:
                job["status"] = "error"
                job["error"] = error
                job["finished_at"] = time.time()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "running":
                return False
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
            return True

    def request_cancel(self, job_id: str) -> bool:
        """Signal cancel without immediately changing the job status.

        The background thread polls is_cancel_requested() between pushes, runs
        rollback, then calls complete() with cancelled=True in the result.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "running":
                return False
            job["status"] = "cancel_requested"
            return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job["status"] == "cancel_requested")

    def snapshot(
        self, job_id: str
    ) -> Optional[Tuple[List[dict], str, Optional[dict], Optional[str]]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return (
                list(job["events"]),
                job["status"],
                job.get("result"),
                job.get("error"),
            )

    def describe(self, job_id: str) -> Optional[dict]:
        """Status metadata for a job, without the full event list."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return {
                "job_id": job_id,
                "status": job["status"],
                "key": job["key"],
                "started_at": job["started_at"],
                "events": len(job["events"]),
            }


store = _JobStore()


def import_job_key(tenant_id: int, product: str) -> str:
    """Job key for a per-tenant, per-product config import."""
    return f"import:{tenant_id}:{product.upper()}"
