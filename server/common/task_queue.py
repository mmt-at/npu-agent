"""Thread-safe task queue shared by scheduling services."""

from __future__ import annotations

import threading
from collections import deque

from server.common.service_config import TaskStatus
from server.common.service_logger import setup_logger
from server.common.service_models import Task
from server.common.task_refs import format_task_ref
from server.common.timezone import now_timestamp

logger = setup_logger("task_queue")


class TaskQueue:
    """Thread-safe task queue with global and per-resource queues."""

    def __init__(self):
        self.lock = threading.RLock()
        self.global_queue: deque[Task] = deque()
        self.resource_queues: dict[int, deque[Task]] = {}
        self.tasks: dict[str, Task] = {}

    def submit_task(self, task: Task) -> str:
        with self.lock:
            task.status = TaskStatus.PENDING
            self.tasks[task.task_id] = task
            self.global_queue.append(task)
            task.timer.start("total")
            task.timer.start("waiting")
            task.timer.start("pending")

        type_info = f", type={task.task_type.value}" if task.task_type else ""
        label_info = f", label={task.task_label}" if task.task_label else ""
        logger.info(
            "TASK %s submitted: mode=%s%s%s, script=%s, resource=%s",
            format_task_ref(task),
            task.task_mode.value,
            type_info,
            label_info,
            task.script_path,
            task.resource_id,
        )
        return task.task_id

    def push_front(self, task: Task):
        with self.lock:
            task.status = TaskStatus.PENDING
            task.assigned_resource = None
            task.queued_timestamp = None
            task.start_timestamp = None
            task.end_timestamp = None
            self.global_queue.appendleft(task)
            task.timer.start("pending")
            logger.info("TASK %s requeued at front", format_task_ref(task))

    def get_task(self, task_id: str) -> Task | None:
        with self.lock:
            return self.tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        with self.lock:
            if status:
                return [task for task in self.tasks.values() if task.status == status]
            return list(self.tasks.values())

    def pop_pending_task(self) -> Task | None:
        with self.lock:
            if not self.global_queue:
                return None
            return self.global_queue.popleft()

    def queue_task_for_resource(self, task: Task, resource_id: int):
        with self.lock:
            if resource_id not in self.resource_queues:
                self.resource_queues[resource_id] = deque()

            task.status = TaskStatus.QUEUED
            task.assigned_resource = resource_id
            task.queued_timestamp = now_timestamp()

            pending_duration = task.timer.stop("pending")
            if pending_duration is not None:
                task.phase_duration_ms["pending"] = pending_duration
            task.timer.start("queue")
            self.resource_queues[resource_id].append(task)

            logger.info("TASK %s queued for resource %s", format_task_ref(task), resource_id)

    def pop_resource_task(self, resource_id: int) -> Task | None:
        with self.lock:
            if resource_id not in self.resource_queues or not self.resource_queues[resource_id]:
                return None
            return self.resource_queues[resource_id].popleft()

    def get_queue_size(self, resource_id: int | None = None) -> int:
        with self.lock:
            if resource_id is None:
                return len(self.global_queue)
            return len(self.resource_queues.get(resource_id, []))

    def cancel_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False

            if task.status not in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                logger.error("Cannot cancel TASK %s with status %s", format_task_ref(task), task.status.value)
                return False

            self._finalize_timing_on_cancel(task)

            try:
                self.global_queue.remove(task)
            except ValueError:
                pass

            if task.assigned_resource is not None:
                resource_id = task.assigned_resource
                if resource_id in self.resource_queues:
                    try:
                        self.resource_queues[resource_id].remove(task)
                    except ValueError:
                        pass

            task.status = TaskStatus.CANCELLED
            logger.info("TASK %s cancelled successfully", format_task_ref(task))
            return True

    def force_cancel_task(self, task_id: str, task_runner) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.error("Cannot force cancel TASK %s: not found", task_id)
                return False

            if task.status in [TaskStatus.PENDING, TaskStatus.QUEUED]:
                return self.cancel_task(task_id)

            if task.status == TaskStatus.RUNNING:
                logger.info("Force cancelling running TASK %s", format_task_ref(task))
                if task_runner.kill_task(task):
                    task.status = TaskStatus.CANCELLED
                    task.error_message = "Cancelled by user (force)"
                    task.end_timestamp = now_timestamp()
                    logger.info("TASK %s force cancelled", format_task_ref(task))
                    return True
                logger.error("Failed to kill running TASK %s", format_task_ref(task))
                return False

            logger.warning("Cannot cancel TASK %s with status %s", format_task_ref(task), task.status.value)
            return False

    def get_statistics(self) -> dict:
        with self.lock:
            return {
                "global_queue_size": len(self.global_queue),
                "total_tasks": len(self.tasks),
                "pending": sum(1 for task in self.tasks.values() if task.status == TaskStatus.PENDING),
                "queued": sum(1 for task in self.tasks.values() if task.status == TaskStatus.QUEUED),
                "running": sum(1 for task in self.tasks.values() if task.status == TaskStatus.RUNNING),
                "completed": sum(1 for task in self.tasks.values() if task.status == TaskStatus.COMPLETED),
                "failed": sum(1 for task in self.tasks.values() if task.status == TaskStatus.FAILED),
                "resource_queues": {
                    resource_id: len(queue) for resource_id, queue in self.resource_queues.items()
                },
            }

    def _finalize_timing_on_cancel(self, task: Task) -> None:
        if task.status == TaskStatus.PENDING:
            pending_duration = task.timer.stop("pending")
            if pending_duration is not None:
                task.phase_duration_ms["pending"] = pending_duration
        if task.status == TaskStatus.QUEUED:
            queue_duration = task.timer.stop("queue")
            if queue_duration is not None:
                task.phase_duration_ms["queue"] = queue_duration
        waiting_duration = task.timer.stop("waiting")
        if waiting_duration is not None:
            task.phase_duration_ms["waiting"] = waiting_duration
        total_duration = task.timer.stop("total")
        if total_duration is not None:
            task.phase_duration_ms["total"] = total_duration


__all__ = ["TaskQueue"]
