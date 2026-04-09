"""Generic models for scheduling services."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import uuid

from server.common.service_config import ResourceMode, ResourceStatus, TaskMode, TaskStatus, TaskType
from server.common.task_timer import TaskTimer
from server.common.timezone import ensure_timezone, now_timestamp


@dataclass
class ComputeResource:
    """Managed compute resource."""

    resource_id: int
    mode: ResourceMode = ResourceMode.SHARED
    status: ResourceStatus = ResourceStatus.ONLINE
    memory_threshold: float = 0.75
    max_concurrent_tasks: int = 3
    current_memory_usage: float = 0.0
    running_tasks: list[str] = field(default_factory=list)
    error_message: str | None = None
    last_error_timestamp: datetime | None = None
    manual_mode: ResourceMode | None = None
    mode_locked_by: str | None = None

    def can_accept_task(self, task_mode: TaskMode | None = None) -> bool:
        if self.status != ResourceStatus.ONLINE:
            return False

        effective_mode = self.manual_mode if self.manual_mode else self.mode

        if task_mode == TaskMode.EXCLUSIVE:
            return len(self.running_tasks) == 0

        if task_mode == TaskMode.SHARED:
            if effective_mode == ResourceMode.EXCLUSIVE and self.running_tasks:
                return False
            if len(self.running_tasks) >= self.max_concurrent_tasks:
                return False
            return self.current_memory_usage < self.memory_threshold

        if effective_mode == ResourceMode.EXCLUSIVE:
            return len(self.running_tasks) == 0

        if len(self.running_tasks) >= self.max_concurrent_tasks:
            return False

        return self.current_memory_usage < self.memory_threshold

    def is_available(self) -> bool:
        return self.status == ResourceStatus.ONLINE


@dataclass
class Task:
    """Task representation."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_mode: TaskMode = TaskMode.SHARED
    task_type: TaskType | None = None
    task_label: str | None = None
    script_path: str = ""
    work_dir: str = "."
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    resource_id: int | None = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_resource: int | None = None
    submit_timestamp: datetime = field(default_factory=now_timestamp)
    queued_timestamp: datetime | None = None
    start_timestamp: datetime | None = None
    end_timestamp: datetime | None = None
    exit_code: int | None = None
    log_file: str | None = None
    error_message: str | None = None
    stdout_size: int = 0
    stderr_size: int = 0
    execution_duration_ms: float | None = None
    phase_duration_ms: dict[str, float] = field(default_factory=dict)
    requeue_count: int = 0
    last_requeue_reason: str | None = None
    timer: TaskTimer = field(default_factory=TaskTimer, repr=False, compare=False)

    @property
    def pending_duration_ms(self) -> float | None:
        duration = self.phase_duration_ms.get("pending")
        if duration is not None:
            return round(duration, 3)
        if self.queued_timestamp:
            return round((self.queued_timestamp - self.submit_timestamp).total_seconds() * 1000, 3)
        return None

    @property
    def queue_duration_ms(self) -> float | None:
        duration = self.phase_duration_ms.get("queue")
        if duration is not None:
            return round(duration, 3)
        if self.queued_timestamp and self.start_timestamp:
            return round((self.start_timestamp - self.queued_timestamp).total_seconds() * 1000, 3)
        return None

    @property
    def waiting_duration_ms(self) -> float | None:
        duration = self.phase_duration_ms.get("waiting")
        if duration is not None:
            return round(duration, 3)
        if self.start_timestamp:
            return round((self.start_timestamp - self.submit_timestamp).total_seconds() * 1000, 3)
        return None

    @property
    def running_duration_ms(self) -> float | None:
        duration = self.phase_duration_ms.get("running")
        if duration is not None:
            return round(duration, 3)
        if self.start_timestamp and self.end_timestamp:
            return round((self.end_timestamp - self.start_timestamp).total_seconds() * 1000, 3)
        return None

    @property
    def total_duration_ms(self) -> float | None:
        duration = self.phase_duration_ms.get("total")
        if duration is not None:
            return round(duration, 3)
        if self.end_timestamp:
            return round((self.end_timestamp - self.submit_timestamp).total_seconds() * 1000, 3)
        return None

    def to_dict(self) -> dict[str, Any]:
        submit_timestamp = ensure_timezone(self.submit_timestamp) if self.submit_timestamp else None
        queued_timestamp = ensure_timezone(self.queued_timestamp) if self.queued_timestamp else None
        start_timestamp = ensure_timezone(self.start_timestamp) if self.start_timestamp else None
        end_timestamp = ensure_timezone(self.end_timestamp) if self.end_timestamp else None

        payload = {
            "task_id": self.task_id,
            "task_mode": self.task_mode.value,
            "script_path": self.script_path,
            "work_dir": self.work_dir,
            "args": self.args,
            "resource_id": self.resource_id,
            "assigned_resource": self.assigned_resource,
            "status": self.status.value,
            "submit_timestamp": submit_timestamp.isoformat() if submit_timestamp else None,
            "queued_timestamp": queued_timestamp.isoformat() if queued_timestamp else None,
            "start_timestamp": start_timestamp.isoformat() if start_timestamp else None,
            "end_timestamp": end_timestamp.isoformat() if end_timestamp else None,
            "exit_code": self.exit_code,
            "log_file": self.log_file,
            "error_message": self.error_message,
            "stdout_size": self.stdout_size,
            "stderr_size": self.stderr_size,
            "pending_duration_ms": self.pending_duration_ms,
            "queue_duration_ms": self.queue_duration_ms,
            "waiting_duration_ms": self.waiting_duration_ms,
            "running_duration_ms": self.running_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "execution_duration_ms": self.execution_duration_ms,
            "requeue_count": self.requeue_count,
            "last_requeue_reason": self.last_requeue_reason,
        }

        if self.task_type is not None:
            payload["task_type"] = self.task_type.value
        if self.task_label is not None:
            payload["task_label"] = self.task_label
        return payload


__all__ = ["ComputeResource", "Task"]
