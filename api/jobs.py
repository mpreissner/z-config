"""In-memory job store for background tasks that stream progress via SSE."""
import uuid
import threading
from typing import Dict, Any, List, Optional, Tuple


class _JobStore:
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "status": "running",
                "events": [],
                "result": None,
                "error": None,
            }
        return job_id

    def append(self, job_id: str, event: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job["events"].append(event)

    def complete(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job["status"] in ("running", "cancel_requested"):
                job["status"] = "done"
                job["result"] = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job["status"] in ("running", "cancel_requested"):
                job["status"] = "error"
                job["error"] = error

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "running":
                return False
            job["status"] = "cancelled"
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


store = _JobStore()
