"""Configuration aliases for the NPU server."""

from server.common.service_config import (
    LoadBalancingStrategy,
    ResourceMode as NPUMode,
    ResourceStatus as NPUStatus,
    ServerConfig,
    TaskMode,
    TaskStatus,
    TaskType,
    config,
)

__all__ = [
    "LoadBalancingStrategy",
    "NPUMode",
    "NPUStatus",
    "ServerConfig",
    "TaskMode",
    "TaskStatus",
    "TaskType",
    "config",
]
