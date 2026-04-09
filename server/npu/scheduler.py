"""Scheduler for NPU server."""

from server.common.scheduler import Scheduler as _BaseScheduler


class Scheduler(_BaseScheduler):
    def resource_label(self) -> str:
        return "NPU"


__all__ = ["Scheduler"]
