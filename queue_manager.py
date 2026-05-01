import queue
import threading
import uuid
from itertools import count
from typing import Dict, List

from terminal_logger import log


JOB_STATUSES = ("pending", "running", "publishing", "completed", "failed")
REPO_PROFILES = {
    "payment-api": {
        "language": "python",
        "priority_rank": 0,
        "branches": ["main", "release/2026.05"],
    },
    "storefront-web": {
        "language": "node",
        "priority_rank": 1,
        "branches": ["main", "hotfix/cart-checkout"],
    },
    "analytics-worker": {
        "language": "python",
        "priority_rank": 2,
        "branches": ["develop", "feature/pipeline-metrics"],
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
        self.sequence = count()
        self.dispatch_sequence = count()
        self.next_publish_order = 0
        self.resolved_publish_orders: set[int] = set()

    def create_job(self, repo: str, language: str, branch: str) -> dict:
        priority_value, priority_reason = self._calculate_priority(repo=repo, branch=branch)
        sequence_number = next(self.sequence)
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
        }
        with self.lock:
            self.jobs[job["id"]] = job.copy()
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
        return sorted(jobs, key=lambda job: (job["priority"], job["enqueue_order"]))

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
        return [
            {
                "repo": repo,
                "language": profile["language"],
                "priority_rank": profile["priority_rank"],
                "branches": profile["branches"],
            }
            for repo, profile in REPO_PROFILES.items()
        ]

    def resolve_language(self, repo: str, language: str) -> str:
        normalized_repo = repo.strip().lower()
        profile = REPO_PROFILES.get(normalized_repo)
        if profile:
            return str(profile["language"]).strip().lower()
        return (language or "generic").strip().lower()

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
