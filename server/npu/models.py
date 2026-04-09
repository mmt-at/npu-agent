"""Data model aliases for the NPU server."""

from server.common.service_config import ResourceMode as NPUMode
from server.common.service_config import ResourceStatus as NPUStatus
from server.common.service_config import TaskMode, TaskStatus, TaskType
from server.common.service_models import ComputeResource as NPU
from server.common.service_models import Task

__all__ = [
    "NPU",
    "NPUMode",
    "NPUStatus",
    "Task",
    "TaskMode",
    "TaskStatus",
    "TaskType",
]
