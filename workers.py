import random
import threading
import time

from queue_manager import JobQueueManager
from repo_manager import GitRepoManager
from terminal_logger import log


class BaseWorker:
    worker_name = "generic"

    def __init__(self, queue_manager: JobQueueManager, repo_manager: GitRepoManager) -> None:
        self.queue_manager = queue_manager
        self.repo_manager = repo_manager

    def run_job(self, job: dict) -> threading.Thread:
        thread = threading.Thread(
            target=self._execute_job,
            args=(job.copy(),),
            daemon=True,
            name=f"{self.worker_name}-worker-{job['id'][:8]}",
        )
        thread.start()
        return thread

    def _execute_job(self, job: dict) -> None:
        self.queue_manager.update_status(job["id"], "running")
        startup_delay = random.uniform(0.3, 1.4)
        log(
            f"[WORKER:{self.worker_name}] job started id={job['id']} "
            f"repo={job['repo']} branch={job['branch']} "
            f"priority={job['priority']} load_delay={startup_delay:.2f}s"
        )
        time.sleep(startup_delay)

        execution_delay = random.uniform(2.0, 6.0)
        log(
            f"[WORKER:{self.worker_name}] executing id={job['id']} "
            f"language={job['language']} branch={job['branch']} "
            f"duration={execution_delay:.2f}s"
        )
        time.sleep(execution_delay)

        if random.random() < 0.2:
            self.queue_manager.update_status(job["id"], "failed")
            self.queue_manager.set_job_fields(
                job["id"],
                sync_status="build_failed",
                sync_error="Simulated build failure before repository publish.",
            )
            self.queue_manager.mark_publish_resolved(job["id"])
            log(f"[WORKER:{self.worker_name}] job failed id={job['id']}")
            return

        publish_job = self.queue_manager.wait_for_publish_turn(job["id"])
        if not publish_job:
            return

        log(
            f"[WORKER:{self.worker_name}] publishing id={publish_job['id']} "
            f"dispatch_order={publish_job['dispatch_order']} "
            f"priority={publish_job['priority']}"
        )
        try:
            sync_result = self.repo_manager.apply_job_update(publish_job)
            final_status = (
                "completed" if sync_result["push_status"] != "push_failed" else "failed"
            )
            self.queue_manager.update_status(job["id"], final_status)
            self.queue_manager.set_job_fields(
                job["id"],
                git_branch=sync_result["target_branch"],
                commit_sha=sync_result["commit_sha"],
                sync_status=sync_result["push_status"],
                sync_error=sync_result["push_error"],
                repository_url=sync_result["repository_url"],
                artifact_path=sync_result["artifact_path"],
            )
            log(
                f"[WORKER:{self.worker_name}] job {final_status} id={job['id']} "
                f"git_branch={sync_result['target_branch']} "
                f"sync_status={sync_result['push_status']}"
            )
        except Exception as exc:
            self.queue_manager.update_status(job["id"], "failed")
            self.queue_manager.set_job_fields(
                job["id"],
                sync_status="publish_exception",
                sync_error=str(exc),
            )
            log(f"[WORKER:{self.worker_name}] publish exception id={job['id']} error={exc}")
        finally:
            self.queue_manager.mark_publish_resolved(job["id"])


class PythonWorker(BaseWorker):
    worker_name = "python"


class NodeWorker(BaseWorker):
    worker_name = "node"


class GenericWorker(BaseWorker):
    worker_name = "generic"
