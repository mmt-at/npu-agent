"""Generic configuration and enums for task-scheduling services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResourceMode(str, Enum):
    """Execution mode for a compute resource."""

    EXCLUSIVE = "exclusive"
    SHARED = "shared"


class TaskType(str, Enum):
    """Business-level task categorization."""

    FUNCTIONAL = "functional"
    PERFORMANCE = "performance"
    BOTH = "both"


class TaskMode(str, Enum):
    """Execution-mode requirement for a task."""

    EXCLUSIVE = "exclusive"
    SHARED = "shared"


class TaskStatus(str, Enum):
    """Lifecycle state for a submitted task."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceStatus(str, Enum):
    """Health state for a managed resource."""

    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class LoadBalancingStrategy(str, Enum):
    """Supported scheduling strategies."""

    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    FILL = "fill"


@dataclass
class ServerConfig:
    """Shared server configuration."""

    host: str = "0.0.0.0"
    port: int = 8080
    log_file: str | None = None
    log_level: str = "DEBUG"
    timezone: str = "Asia/Shanghai"
    default_resource_mode: ResourceMode = ResourceMode.SHARED
    default_memory_threshold: float = 0.75
    default_max_concurrent_tasks: int = 3
    task_timeout: int = 600
    error_pause_duration: int = 60
    scheduler_interval: float = 1.0
    resource_monitor_interval: float = 5.0
    load_balancing_strategy: LoadBalancingStrategy | None = None


config = ServerConfig()


__all__ = [
    "LoadBalancingStrategy",
    "ResourceMode",
    "ResourceStatus",
    "ServerConfig",
    "TaskMode",
    "TaskStatus",
    "TaskType",
    "config",
]
