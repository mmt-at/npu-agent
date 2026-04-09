"""Generic resource manager shared by scheduling services."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from server.common.service_config import (
    LoadBalancingStrategy,
    ResourceMode,
    ResourceStatus,
    TaskMode,
    TaskStatus,
    config,
)
from server.common.service_logger import setup_logger
from server.common.service_models import ComputeResource, Task
from server.common.task_refs import format_task_ref
from server.common.timezone import now_timestamp
from server.common.timer import monotonic_elapsed_ms, monotonic_timestamp_ns

if TYPE_CHECKING:
    from server.common.task_queue import TaskQueue
    from server.common.subprocess_task_runner import SubprocessTaskRunner

logger = setup_logger("resource_manager")


class ResourceManager:
    """Manages compute resources, monitoring, and status."""

    def __init__(self):
        self.resources: dict[int, ComputeResource] = {}
        self.lock = threading.RLock()
        self.monitor_thread: threading.Thread | None = None
        self.running = False
        self.monitor_initialized = False
        self.monitor_device_count = 0
        self.severe_error_active = False
        self.severe_error_timestamp = None
        self.severe_error_monotonic_ns: int | None = None
        self.error_resources: set[int] = set()
        self.resource_error_monotonic_ns: dict[int, int] = {}
        self._round_robin_cursor: int = -1
        self.task_queue: TaskQueue | None = None
        self.task_runner: SubprocessTaskRunner | None = None
        self._initialize_monitor()

    def resource_label(self) -> str:
        return "resource"

    def device_error_keywords(self) -> tuple[str, ...]:
        return ("resource error", "out of memory")

    def _initialize_monitor(self):
        self.monitor_initialized = False
        self.monitor_device_count = 0

    def _update_resource_memory(self, resource_id: int):
        return None

    def clear_stale_running_tasks(self):
        with self.lock:
            cleared_count = 0
            for resource_id, resource in self.resources.items():
                if resource.running_tasks:
                    stale_count = len(resource.running_tasks)
                    logger.warning(
                        "Clearing %d stale running tasks from %s %s: %s",
                        stale_count,
                        self.resource_label(),
                        resource_id,
                        resource.running_tasks,
                    )
                    resource.running_tasks.clear()
                    cleared_count += stale_count
            if cleared_count > 0:
                logger.info("Cleared %d stale running tasks from all resources", cleared_count)

    def set_dependencies(self, task_queue: TaskQueue, task_runner: SubprocessTaskRunner):
        self.task_queue = task_queue
        self.task_runner = task_runner
        logger.debug("Resource manager dependencies set")

    def register_resource(
        self,
        resource_id: int,
        mode: ResourceMode | None = None,
        memory_threshold: float | None = None,
        max_concurrent_tasks: int | None = None,
    ) -> bool:
        with self.lock:
            if resource_id in self.resources:
                logger.warning("%s %s already registered", self.resource_label().capitalize(), resource_id)
                return False

            resource = ComputeResource(
                resource_id=resource_id,
                mode=mode or config.default_resource_mode,
                memory_threshold=memory_threshold or config.default_memory_threshold,
                max_concurrent_tasks=max_concurrent_tasks or config.default_max_concurrent_tasks,
                status=ResourceStatus.ONLINE,
            )
            self.resources[resource_id] = resource
            if config.load_balancing_strategy == LoadBalancingStrategy.ROUND_ROBIN:
                self._round_robin_cursor = -1
            logger.info(
                "Registered %s %s with mode=%s, threshold=%s, max_tasks=%s",
                self.resource_label(),
                resource_id,
                resource.mode,
                resource.memory_threshold,
                resource.max_concurrent_tasks,
            )
            return True

    def unregister_resource(self, resource_id: int) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                logger.warning("%s %s not registered", self.resource_label().capitalize(), resource_id)
                return False
            resource = self.resources[resource_id]
            if resource.running_tasks:
                logger.error(
                    "Cannot unregister %s %s: has running tasks",
                    self.resource_label(),
                    resource_id,
                )
                return False
            del self.resources[resource_id]
            if config.load_balancing_strategy == LoadBalancingStrategy.ROUND_ROBIN:
                self._round_robin_cursor = -1
            logger.info("Unregistered %s %s", self.resource_label(), resource_id)
            return True

    def set_resource_status(self, resource_id: int, status: ResourceStatus) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            self.resources[resource_id].status = status
            logger.info("%s %s status changed to %s", self.resource_label().capitalize(), resource_id, status.value)
            return True

    def set_resource_mode(self, resource_id: int, mode: ResourceMode, manual: bool = True) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            resource = self.resources[resource_id]
            resource.mode = mode
            if manual:
                resource.manual_mode = mode
                logger.info("%s %s manual mode set to %s", self.resource_label().capitalize(), resource_id, mode.value)
            else:
                logger.debug("%s %s mode changed to %s (task-driven)", self.resource_label().capitalize(), resource_id, mode.value)
            return True

    def clear_manual_mode(self, resource_id: int) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            self.resources[resource_id].manual_mode = None
            logger.info("%s %s manual mode cleared", self.resource_label().capitalize(), resource_id)
            return True

    def set_resource_mode_for_task(
        self,
        resource_id: int,
        task: Task,
        task_mode_override: TaskMode | None = None,
    ) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            resource = self.resources[resource_id]
            if resource.manual_mode:
                logger.debug(
                    "%s %s has manual mode %s, not changing for task %s",
                    self.resource_label().capitalize(),
                    resource_id,
                    resource.manual_mode.value,
                    format_task_ref(task),
                )
                return True

            effective_task_mode = task_mode_override or task.task_mode
            if effective_task_mode == TaskMode.EXCLUSIVE:
                resource.mode = ResourceMode.EXCLUSIVE
                resource.mode_locked_by = task.task_id
                logger.info(
                    "%s %s mode set to EXCLUSIVE for task %s",
                    self.resource_label().capitalize(),
                    resource_id,
                    format_task_ref(task),
                )
            else:
                if not resource.mode_locked_by:
                    resource.mode = ResourceMode.SHARED
                    logger.debug(
                        "%s %s mode set to SHARED for task %s",
                        self.resource_label().capitalize(),
                        resource_id,
                        format_task_ref(task),
                    )
            return True

    def restore_resource_mode_after_task(self, resource_id: int, task: Task) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            resource = self.resources[resource_id]
            if resource.mode_locked_by == task.task_id:
                resource.mode_locked_by = None
                logger.debug(
                    "%s %s mode unlocked by TASK %s",
                    self.resource_label().capitalize(),
                    resource_id,
                    format_task_ref(task),
                )
                if resource.manual_mode:
                    resource.mode = resource.manual_mode
                elif not resource.running_tasks:
                    resource.mode = ResourceMode.SHARED
            return True

    def set_resource_memory_threshold(self, resource_id: int, threshold: float) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            if not 0 < threshold <= 1.0:
                logger.error("Invalid threshold %s, must be between 0 and 1", threshold)
                return False
            self.resources[resource_id].memory_threshold = threshold
            logger.info("%s %s memory threshold set to %s", self.resource_label().capitalize(), resource_id, threshold)
            return True

    def set_resource_max_concurrent_tasks(self, resource_id: int, max_tasks: int) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            if max_tasks < 1:
                logger.error("Invalid max_tasks %s, must be >= 1", max_tasks)
                return False
            self.resources[resource_id].max_concurrent_tasks = max_tasks
            logger.info(
                "%s %s max concurrent tasks set to %s",
                self.resource_label().capitalize(),
                resource_id,
                max_tasks,
            )
            return True

    def get_resource(self, resource_id: int) -> ComputeResource | None:
        with self.lock:
            return self.resources.get(resource_id)

    def list_resources(self) -> list[ComputeResource]:
        with self.lock:
            return list(self.resources.values())

    def find_available_resource(self, preferred_resource: int | None = None, task_mode: TaskMode | None = None) -> int | None:
        if preferred_resource is not None and preferred_resource in self.resources:
            self._update_resource_memory(preferred_resource)
            with self.lock:
                resource = self.resources.get(preferred_resource)
                queued_depth = self.task_queue.get_queue_size(preferred_resource) if resource and self.task_queue else 0
                if not resource:
                    return None
                if resource.status != ResourceStatus.ONLINE or preferred_resource in self.resource_error_monotonic_ns:
                    return None
                if resource.can_accept_task(task_mode) and self._has_queue_capacity(resource, queued_depth, task_mode):
                    return preferred_resource
            return None

        with self.lock:
            resource_ids = list(self.resources.keys())

        for resource_id in resource_ids:
            self._update_resource_memory(resource_id)

        with self.lock:
            if not self.resources:
                return None

            base_order = sorted(self.resources.keys())
            stats: dict[int, tuple[ComputeResource, int, int]] = {}
            for resource_id in base_order:
                resource = self.resources[resource_id]
                queued_depth = self.task_queue.get_queue_size(resource_id) if self.task_queue else 0
                stats[resource_id] = (resource, queued_depth, len(resource.running_tasks))

            strategy = config.load_balancing_strategy
            if strategy == LoadBalancingStrategy.FILL:
                strategy = None

            if strategy == LoadBalancingStrategy.LEAST_LOADED:
                ordered_ids = sorted(
                    base_order,
                    key=lambda rid: (stats[rid][2] + stats[rid][1], stats[rid][1], rid),
                )
            elif strategy == LoadBalancingStrategy.ROUND_ROBIN and base_order:
                start_idx = (self._round_robin_cursor + 1) % len(base_order)
                ordered_ids = base_order[start_idx:] + base_order[:start_idx]
            else:
                ordered_ids = base_order

            for candidate_id in ordered_ids:
                resource, queued_depth, _ = stats[candidate_id]
                if resource.can_accept_task(task_mode) and self._has_queue_capacity(resource, queued_depth, task_mode):
                    if strategy == LoadBalancingStrategy.ROUND_ROBIN:
                        self._set_round_robin_cursor_locked(candidate_id)
                    return candidate_id

        return None

    def _has_queue_capacity(
        self,
        resource: ComputeResource,
        queued_depth: int,
        task_mode: TaskMode | None,
    ) -> bool:
        requested_mode = task_mode or TaskMode.SHARED
        if requested_mode == TaskMode.EXCLUSIVE:
            return queued_depth == 0 and len(resource.running_tasks) == 0
        active_count = len(resource.running_tasks) + queued_depth
        return active_count < resource.max_concurrent_tasks

    def _set_round_robin_cursor_locked(self, resource_id: int):
        if config.load_balancing_strategy != LoadBalancingStrategy.ROUND_ROBIN:
            return
        if not self.resources:
            self._round_robin_cursor = -1
            return
        base_order = sorted(self.resources.keys())
        if resource_id in base_order:
            self._round_robin_cursor = base_order.index(resource_id)

    def is_resource_paused(self, resource_id: int) -> bool:
        with self.lock:
            return resource_id in self.resource_error_monotonic_ns

    def should_pause_scheduling(self) -> bool:
        with self.lock:
            if not self.resources:
                return False
            for resource_id, resource in self.resources.items():
                if resource.status != ResourceStatus.ONLINE:
                    continue
                if resource_id not in self.resource_error_monotonic_ns:
                    return False
            return bool(self.resource_error_monotonic_ns)

    def list_paused_resources(self) -> list[int]:
        with self.lock:
            return sorted(self.resource_error_monotonic_ns.keys())

    def mark_task_running(self, resource_id: int, task: Task) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                return False
            self.resources[resource_id].running_tasks.append(task.task_id)
            logger.debug("Task %s running on %s %s", format_task_ref(task), self.resource_label(), resource_id)
            return True

    def mark_task_completed(self, resource_id: int, task: Task) -> bool:
        with self.lock:
            if resource_id not in self.resources:
                logger.warning("Cannot mark task completed: %s %s not found", self.resource_label(), resource_id)
                return False
            resource = self.resources[resource_id]
            if task.task_id in resource.running_tasks:
                resource.running_tasks.remove(task.task_id)
                logger.info(
                    "TASK %s completed on %s %s, remaining running tasks: %s",
                    format_task_ref(task),
                    self.resource_label(),
                    resource_id,
                    len(resource.running_tasks),
                )
            else:
                logger.warning(
                    "TASK %s not found in %s %s running_tasks. Current running_tasks: %s",
                    format_task_ref(task),
                    self.resource_label(),
                    resource_id,
                    resource.running_tasks,
                )
            return True

    def trigger_severe_error(self, resource_id: int, error_msg: str, offending_task_id: str | None = None):
        with self.lock:
            pause_marker = monotonic_timestamp_ns()
            self.severe_error_active = True
            self.severe_error_timestamp = now_timestamp()
            self.severe_error_monotonic_ns = pause_marker

            if resource_id in self.resources:
                resource = self.resources[resource_id]
                resource.status = ResourceStatus.ERROR
                resource.error_message = error_msg
                resource.last_error_timestamp = self.severe_error_timestamp
                self.error_resources.add(resource_id)
                self.resource_error_monotonic_ns[resource_id] = pause_marker
                running_task_ids = list(resource.running_tasks)
            else:
                running_task_ids = []

            logger.error(
                "SEVERE ERROR on %s %s: %s. Killing %d running tasks.",
                self.resource_label(),
                resource_id,
                error_msg,
                len(running_task_ids),
            )

        if self.task_queue and self.task_runner and running_task_ids:
            damage_message = f"{self.resource_label()} damage bug: {error_msg}"
            trigger_note = (
                f"triggered by task {offending_task_id}"
                if offending_task_id
                else "triggered by severe error"
            )

            def _mark_task_failed(task: Task):
                if task.status != TaskStatus.CANCELLED:
                    task.status = TaskStatus.FAILED
                if task.error_message:
                    if damage_message not in task.error_message:
                        task.error_message = f"{task.error_message} | {damage_message}"
                else:
                    task.error_message = damage_message
                if task.end_timestamp is None:
                    task.end_timestamp = now_timestamp()
                logger.info("Marked TASK %s as failed due to severe error (no retry)", format_task_ref(task))

            collateral_tasks: list[Task] = []

            for task_id in running_task_ids:
                task = self.task_queue.get_task(task_id)
                if not task:
                    continue

                if offending_task_id and task.task_id != offending_task_id:
                    reason = f"{self.resource_label()} {resource_id} severe error {trigger_note}"
                    task.last_requeue_reason = reason
                    kill_success = False
                    try:
                        kill_success = self.task_runner.kill_task(task)
                    except Exception as exc:
                        logger.error("Error while killing TASK %s: %s", format_task_ref(task), exc, exc_info=True)
                    if kill_success:
                        logger.info("Killed TASK %s due to severe error", format_task_ref(task))
                    else:
                        logger.warning("Could not terminate TASK %s (maybe already exited)", format_task_ref(task))
                    task.error_message = f"Killed due to {reason}"
                    collateral_tasks.append(task)
                else:
                    kill_success = False
                    try:
                        kill_success = self.task_runner.kill_task(task)
                    except Exception as exc:
                        logger.error("Error while killing TASK %s: %s", format_task_ref(task), exc, exc_info=True)
                    if kill_success:
                        logger.info("Killed TASK %s due to severe error", format_task_ref(task))
                    else:
                        logger.warning("Could not terminate TASK %s (maybe already exited)", format_task_ref(task))
                    _mark_task_failed(task)

            for task in reversed(collateral_tasks):
                task.start_timestamp = None
                task.end_timestamp = None
                task.exit_code = None
                task.stdout_size = 0
                task.stderr_size = 0
                task.phase_duration_ms.clear()
                task.execution_duration_ms = None
                task.timer.reset()
                task.requeue_count += 1
                reason = task.last_requeue_reason or f"{self.resource_label()} {resource_id} severe error {trigger_note}"
                task.last_requeue_reason = reason
                task.error_message = f"Requeued after {reason}"
                self.task_queue.push_front(task)
                logger.info(
                    "Requeued collateral TASK %s after severe error on %s %s",
                    format_task_ref(task),
                    self.resource_label(),
                    resource_id,
                )

            with self.lock:
                if resource_id in self.resources:
                    cleared_count = len(self.resources[resource_id].running_tasks)
                    self.resources[resource_id].running_tasks.clear()
                    logger.info("Cleared %d tasks from %s %s", cleared_count, self.resource_label(), resource_id)

        remaining_online = 0
        with self.lock:
            for _, resource in self.resources.items():
                if resource.status == ResourceStatus.ONLINE:
                    remaining_online += 1
        logger.error(
            "%s %s paused for %ss due to severe error. %d other resource(s) remain available for scheduling.",
            self.resource_label().capitalize(),
            resource_id,
            config.error_pause_duration,
            remaining_online,
        )

    def _clear_resource_error_locked(self, resource_id: int):
        resource = self.resources.get(resource_id)
        if resource:
            resource.status = ResourceStatus.ONLINE
            resource.error_message = None
            logger.info("%s %s recovered from severe error and is back online", self.resource_label().capitalize(), resource_id)
        self.error_resources.discard(resource_id)
        self.resource_error_monotonic_ns.pop(resource_id, None)

    def clear_severe_error(self, resource_id: int | None = None):
        with self.lock:
            if resource_id is not None:
                self._clear_resource_error_locked(resource_id)
            else:
                for error_resource_id in list(self.error_resources):
                    self._clear_resource_error_locked(error_resource_id)

            self.severe_error_active = bool(self.error_resources)
            if not self.severe_error_active:
                self.severe_error_timestamp = None
                self.severe_error_monotonic_ns = None
                logger.info("All resources recovered from severe errors, resuming full operations")

    def start_monitoring(self):
        if self.running:
            logger.warning("Resource monitor already running")
            return
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Resource monitor started")

    def stop_monitoring(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Resource monitor stopped")

    def _monitor_loop(self):
        while self.running:
            try:
                with self.lock:
                    resource_ids = list(self.resources.keys())

                for resource_id in resource_ids:
                    self._update_resource_memory(resource_id)

                with self.lock:
                    paused_resources = list(self.resource_error_monotonic_ns.items())

                for paused_resource_id, start_ns in paused_resources:
                    elapsed_ms = monotonic_elapsed_ms(start_ns)
                    if elapsed_ms > config.error_pause_duration * 1000:
                        logger.info(
                            "%s %s pause duration (%ss) elapsed, auto-resuming",
                            self.resource_label().capitalize(),
                            paused_resource_id,
                            config.error_pause_duration,
                        )
                        self.clear_severe_error(paused_resource_id)
            except Exception as exc:
                logger.error("Error in resource monitor loop: %s", exc, exc_info=True)
            time.sleep(config.resource_monitor_interval)


__all__ = ["ResourceManager"]
