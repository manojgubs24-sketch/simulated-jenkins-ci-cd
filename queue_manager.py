import queue
import threading
import uuid
from datetime import datetime, timezone
from itertools import count
from typing import Dict, List

from terminal_logger import log


JOB_STATUSES = ("pending", "running", "publishing", "completed", "failed")
REPO_PROFILES = {
    "payment-api": {
        "language": "python",
        "priority_rank": 0,
        "branches": ["main", "release/2026.05", "hotfix/refund-timeout"],
    },
    "storefront-web": {
        "language": "node",
        "priority_rank": 1,
        "branches": ["main", "hotfix/cart-checkout", "release/summer-campaign"],
    },
    "analytics-worker": {
        "language": "python",
        "priority_rank": 2,
        "branches": ["develop", "feature/pipeline-metrics", "main"],
    },
    "identity-service": {
        "language": "python",
        "priority_rank": 3,
        "branches": ["main", "develop", "feature/oauth-audit"],
    },
    "notifications-hub": {
        "language": "node",
        "priority_rank": 4,
        "branches": ["main", "release/notification-v2", "feature/sms-retry"],
    },
}
BRANCH_PRIORITY_RULES = (
    ("main", 0, "production branch"),
    ("master", 0, "production branch"),
    ("release/", 1, "release stabilization branch"),
    ("hotfix/", 2, "hotfix branch"),
    ("develop", 3, "shared integration branch"),
    ("feature/", 4, "feature branch"),
)


class JobQueueManager:
    def __init__(self) -> None:
        self.job_queue: queue.PriorityQueue[tuple[int, int, dict]] = queue.PriorityQueue()
        self.jobs: Dict[str, dict] = {}
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.history: List[dict] = []
        self.history_sequence = count()
        self.sequence = count()
        self.dispatch_sequence = count()
        self.next_publish_order = 0
        self.resolved_publish_orders: set[int] = set()

    def create_job(self, repo: str, language: str, branch: str) -> dict:
        priority_value, priority_reason = self._calculate_priority(repo=repo, branch=branch)
        sequence_number = next(self.sequence)
        created_at = self._timestamp()
        job = {
            "id": str(uuid.uuid4()),
            "repo": repo,
            "branch": branch,
            "language": (language or "generic").strip().lower(),
            "status": "pending",
            "priority": priority_value,
            "priority_reason": priority_reason,
            "enqueue_order": sequence_number,
            "dispatch_order": None,
            "git_branch": None,
            "commit_sha": None,
            "sync_status": "queued",
            "sync_error": None,
            "repository_url": None,
            "artifact_path": None,
            "worker_name": None,
            "created_at": created_at,
            "started_at": None,
            "published_at": None,
            "completed_at": None,
        }
        with self.lock:
            self.jobs[job["id"]] = job.copy()
            self._append_history_locked(
                job,
                event="queued",
                message=(
                    f"Queued {job['repo']} / {job['branch']} "
                    f"with priority {job['priority']}"
                ),
            )
        self.job_queue.put((priority_value, sequence_number, job.copy()))
        log(
            f"[QUEUE] job received id={job['id']} repo={repo} "
            f"branch={branch} language={job['language']} priority={priority_value} "
            f"reason='{priority_reason}' status=pending"
        )
        return job

    def get_next_job(self, timeout: float = 1.0) -> dict | None:
        try:
            _, _, job = self.job_queue.get(timeout=timeout)
            return job
        except queue.Empty:
            return None

    def mark_done(self) -> None:
        self.job_queue.task_done()

    def update_status(self, job_id: str, status: str) -> dict | None:
        if status not in JOB_STATUSES:
            raise ValueError(f"Unsupported job status: {status}")
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            job["status"] = status
            now = self._timestamp()
            if status == "running" and not job["started_at"]:
                job["started_at"] = now
            elif status == "publishing":
                job["published_at"] = now
            elif status in {"completed", "failed"}:
                job["completed_at"] = now
            self._append_history_locked(
                job,
                event=status,
                message=f"Job status changed to {status}",
            )
            return job.copy()

    def set_job_fields(self, job_id: str, **fields) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            job.update(fields)
            return job.copy()

    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.copy() if job else None

    def get_all_jobs(self) -> List[dict]:
        with self.lock:
            jobs = [job.copy() for job in self.jobs.values()]
        return sorted(
            jobs,
            key=lambda job: (
                0 if job["status"] in {"running", "publishing"} else 1,
                job["priority"],
                job["enqueue_order"],
            ),
        )

    def size(self) -> int:
        return self.job_queue.qsize()

    def assign_dispatch_order(self, job_id: str) -> dict | None:
        with self.condition:
            job = self.jobs.get(job_id)
            if not job:
                return None
            if job["dispatch_order"] is None:
                job["dispatch_order"] = next(self.dispatch_sequence)
                job["sync_status"] = "dispatched"
                self._append_history_locked(
                    job,
                    event="dispatched",
                    message=f"Assigned publish order {job['dispatch_order']}",
                )
            return job.copy()

    def wait_for_publish_turn(self, job_id: str) -> dict | None:
        with self.condition:
            while True:
                job = self.jobs.get(job_id)
                if not job:
                    return None
                dispatch_order = job.get("dispatch_order")
                if dispatch_order is None:
                    return job.copy()
                if dispatch_order == self.next_publish_order:
                    job["status"] = "publishing"
                    job["sync_status"] = "publishing"
                    if not job["published_at"]:
                        job["published_at"] = self._timestamp()
                    self._append_history_locked(
                        job,
                        event="publishing",
                        message=(
                            f"Job reached publish turn {job['dispatch_order']} "
                            f"with priority {job['priority']}"
                        ),
                    )
                    return job.copy()
                self.condition.wait(timeout=0.5)

    def mark_publish_resolved(self, job_id: str) -> None:
        with self.condition:
            job = self.jobs.get(job_id)
            if not job or job.get("dispatch_order") is None:
                return
            self.resolved_publish_orders.add(job["dispatch_order"])
            while self.next_publish_order in self.resolved_publish_orders:
                self.resolved_publish_orders.remove(self.next_publish_order)
                self.next_publish_order += 1
            self.condition.notify_all()

    def create_sample_pushes(self) -> List[dict]:
        jobs: List[dict] = []
        for repo, profile in REPO_PROFILES.items():
            for branch in profile["branches"]:
                jobs.append(
                    self.create_job(
                        repo=repo,
                        language=profile["language"],
                        branch=branch,
                    )
                )
        return jobs

    def get_repo_catalog(self) -> List[dict]:
        catalog = []
        for repo, profile in REPO_PROFILES.items():
            branch_details = []
            for branch in profile["branches"]:
                priority, reason = self._calculate_priority(repo=repo, branch=branch)
                branch_details.append(
                    {
                        "name": branch,
                        "priority": priority,
                        "reason": reason,
                    }
                )
            catalog.append(
                {
                    "repo": repo,
                    "language": profile["language"],
                    "priority_rank": profile["priority_rank"],
                    "branches": profile["branches"],
                    "branch_details": branch_details,
                }
            )
        return catalog

    def resolve_language(self, repo: str, language: str) -> str:
        normalized_repo = repo.strip().lower()
        profile = REPO_PROFILES.get(normalized_repo)
        if profile:
            return str(profile["language"]).strip().lower()
        return (language or "generic").strip().lower()

    def record_event(self, job_id: str, event: str, message: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return None
            self._append_history_locked(job, event=event, message=message)
            return job.copy()

    def get_history(self, limit: int = 120) -> List[dict]:
        with self.lock:
            items = [entry.copy() for entry in self.history[-limit:]]
        return list(reversed(items))

    def reset(self) -> None:
        with self.condition:
            self.job_queue = queue.PriorityQueue()
            self.jobs = {}
            self.history = []
            self.sequence = count()
            self.dispatch_sequence = count()
            self.history_sequence = count()
            self.next_publish_order = 0
            self.resolved_publish_orders = set()
            self.condition.notify_all()

    def get_summary(self) -> dict:
        with self.lock:
            jobs = list(self.jobs.values())
        summary = {status: 0 for status in JOB_STATUSES}
        pushed = 0
        for job in jobs:
            summary[job["status"]] += 1
            if job.get("sync_status") in {"pushed", "local_commit_only"}:
                pushed += 1
        return {
            "counts": summary,
            "total_jobs": len(jobs),
            "pushed_jobs": pushed,
            "sample_push_count": self.get_sample_push_count(),
            "repo_count": len(REPO_PROFILES),
        }

    def get_sample_push_count(self) -> int:
        return sum(len(profile["branches"]) for profile in REPO_PROFILES.values())

    def _calculate_priority(self, repo: str, branch: str) -> tuple[int, str]:
        branch_value, branch_reason = self._branch_priority(branch)
        repo_profile = REPO_PROFILES.get(repo.strip().lower())
        repo_rank = repo_profile["priority_rank"] if repo_profile else 9
        repo_reason = (
            f"repo rank {repo_rank} for {repo.strip().lower()}"
            if repo_profile
            else "unknown repo fallback rank"
        )
        priority_value = (branch_value * 10) + repo_rank
        priority_reason = f"{branch_reason}; {repo_reason}"
        return priority_value, priority_reason

    def _branch_priority(self, branch: str) -> tuple[int, str]:
        normalized_branch = branch.strip().lower()
        for prefix, priority_value, reason in BRANCH_PRIORITY_RULES:
            if normalized_branch == prefix or normalized_branch.startswith(prefix):
                return priority_value, reason
        return 5, "other branch"

    def _append_history_locked(self, job: dict, event: str, message: str) -> None:
        self.history.append(
            {
                "sequence": next(self.history_sequence),
                "timestamp": self._timestamp(),
                "event": event,
                "message": message,
                "job_id": job["id"],
                "repo": job["repo"],
                "branch": job["branch"],
                "priority": job["priority"],
                "dispatch_order": job["dispatch_order"],
                "status": job["status"],
                "sync_status": job.get("sync_status"),
                "worker_name": job.get("worker_name"),
            }
        )
        if len(self.history) > 500:
            self.history = self.history[-500:]

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()
