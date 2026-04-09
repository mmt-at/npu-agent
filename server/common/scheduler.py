"""Generic task scheduler."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from server.common.service_config import config
from server.common.service_logger import setup_logger
from server.common.task_refs import format_task_ref

logger = setup_logger("scheduler")


class Scheduler:
    """Schedules and dispatches tasks to available resources."""

    def __init__(self, resource_manager, task_queue, task_runner):
        self.resource_manager = resource_manager
        self.task_queue = task_queue
        self.task_runner = task_runner
        self.running = False
        self.scheduler_thread: threading.Thread | None = None

    def resource_label(self) -> str:
        return "resource"

    def error_keywords(self) -> tuple[str, ...]:
        return self.resource_manager.device_error_keywords()

    def _schedule_round(self):
        while True:
            task = self.task_queue.pop_pending_task()
            if not task:
                break

            resource_id = self.resource_manager.find_available_resource(task.resource_id, task.task_mode)
            if resource_id is None:
                self.task_queue.global_queue.appendleft(task)
                break

            self.task_queue.queue_task_for_resource(task, resource_id)

        for resource in self.resource_manager.list_resources():
            resource_id = resource.resource_id
            task = self.task_queue.pop_resource_task(resource_id)
            if not task:
                continue

            if not resource.can_accept_task(task.task_mode):
                self.task_queue.resource_queues[resource_id].appendleft(task)
                continue

            self.resource_manager.mark_task_running(resource_id, task)
            self.resource_manager.set_resource_mode_for_task(resource_id, task)

            thread = threading.Thread(target=self._execute_task, args=(task, resource_id), daemon=True)
            thread.start()

    def _execute_task(self, task, resource_id: int):
        try:
            success = self.task_runner.run_task(task, resource_id)

            if not success or task.exit_code != 0:
                logger.error(
                    "TASK %s failed with exit code %s",
                    format_task_ref(task),
                    task.exit_code,
                )
                if task.log_file and task.stderr_size > 0 and task.stderr_size < 1024 * 1024:
                    try:
                        stderr_path = Path(task.log_file).parent / f"{task.task_id}.stderr"
                        if stderr_path.exists():
                            stderr_content = stderr_path.read_text(encoding="utf-8", errors="replace").lower()
                            if any(keyword in stderr_content for keyword in self.error_keywords()):
                                self.resource_manager.trigger_severe_error(
                                    resource_id,
                                    f"{self.resource_label()} error in TASK {format_task_ref(task)}",
                                    task.task_id,
                                )
                    except Exception as exc:
                        logger.debug("Could not check stderr for device errors: %s", exc, exc_info=True)
        finally:
            try:
                self.resource_manager.restore_resource_mode_after_task(resource_id, task)
            except Exception as exc:
                logger.error(
                    "Failed to restore %s mode after TASK %s on %s %s: %s",
                    self.resource_label(),
                    format_task_ref(task),
                    self.resource_label(),
                    resource_id,
                    exc,
                    exc_info=True,
                )
            finally:
                try:
                    self.resource_manager.mark_task_completed(resource_id, task)
                except Exception as exc:
                    logger.error(
                        "Failed to mark TASK %s completed on %s %s: %s",
                        format_task_ref(task),
                        self.resource_label(),
                        resource_id,
                        exc,
                        exc_info=True,
                    )

    def _scheduler_loop(self):
        while self.running:
            try:
                if self.resource_manager.should_pause_scheduling():
                    logger.warning("All resources paused due to severe errors, skipping scheduling round")
                    time.sleep(config.scheduler_interval)
                    continue
                self._schedule_round()
            except Exception as exc:
                logger.error("Error in scheduler loop: %s", exc, exc_info=True)
            time.sleep(config.scheduler_interval)

    def start(self):
        if self.running:
            logger.warning("Scheduler already running")
            return
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        logger.info("Scheduler stopped")


__all__ = ["Scheduler"]
