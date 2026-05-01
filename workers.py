import random
import threading
import time

from queue_manager import JobQueueManager
from terminal_logger import log


class BaseWorker:
    worker_name = "generic"

    def __init__(self, queue_manager: JobQueueManager) -> None:
        self.queue_manager = queue_manager

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
            log(f"[WORKER:{self.worker_name}] job failed id={job['id']}")
            return

        self.queue_manager.update_status(job["id"], "completed")
        log(f"[WORKER:{self.worker_name}] job completed id={job['id']}")


class PythonWorker(BaseWorker):
    worker_name = "python"


class NodeWorker(BaseWorker):
    worker_name = "node"


class GenericWorker(BaseWorker):
    worker_name = "generic"
