import random
import threading
import time

from queue_manager import JobQueueManager
from terminal_logger import log
from workers import GenericWorker, NodeWorker, PythonWorker


class Scheduler:
    def __init__(self, queue_manager: JobQueueManager) -> None:
        self.queue_manager = queue_manager
        self.running = False
        self.thread: threading.Thread | None = None
        self.workers = {
            "python": PythonWorker(queue_manager),
            "node": NodeWorker(queue_manager),
        }
        self.fallback_worker = GenericWorker(queue_manager)

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="scheduler-thread",
        )
        self.thread.start()
        log("[SCHEDULER] background scheduler started")

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)

    def _run_loop(self) -> None:
        while self.running:
            job = self.queue_manager.get_next_job(timeout=1.0)
            if job is None:
                continue

            worker = self._select_worker(job.get("language", ""))
            assignment_delay = random.uniform(0.2, 1.2)
            log(
                f"[SCHEDULER] job assigned id={job['id']} "
                f"repo={job['repo']} branch={job['branch']} priority={job['priority']} "
                f"worker={worker.worker_name} queue_size={self.queue_manager.size()} "
                f"assignment_delay={assignment_delay:.2f}s"
            )
            time.sleep(assignment_delay)
            worker.run_job(job)
            self.queue_manager.mark_done()

    def _select_worker(self, language: str):
        normalized = (language or "").strip().lower()
        return self.workers.get(normalized, self.fallback_worker)
