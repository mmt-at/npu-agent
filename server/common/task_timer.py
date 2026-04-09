"""Utilities for measuring task lifecycle phases."""

from __future__ import annotations

from server.common.context import ManagedContext
from server.common.timer import HostTimer, TimerSample, create_host_timer


class TaskTimer:
    """Track task lifecycle using host-side timers."""

    def __init__(self, task_id: str | None = None) -> None:
        self._samples: list[TimerSample] = []
        self._durations_ms: dict[str, float] = {}
        self._active_contexts: dict[str, ManagedContext] = {}
        self._timer: HostTimer = create_host_timer(reporter=self._capture_sample, enabled=True)
        self._task_id = task_id

    def _capture_sample(self, sample: TimerSample) -> None:
        self._samples.append(sample)
        previous = self._durations_ms.get(sample.label, 0.0)
        self._durations_ms[sample.label] = previous + sample.duration_ms

    def start(self, label: str) -> None:
        if label in self._active_contexts:
            return
        ctx = ManagedContext(self._timer.time(label))
        ctx.enter()
        self._active_contexts[label] = ctx

    def stop(self, label: str) -> float | None:
        ctx = self._active_contexts.pop(label, None)
        if not ctx:
            return None
        ctx.exit()
        return self._durations_ms.get(label)

    def get_duration_ms(self, label: str) -> float | None:
        return self._durations_ms.get(label)

    def as_dict(self) -> dict[str, float]:
        return dict(self._durations_ms)

    def reset(self) -> None:
        for label in list(self._active_contexts):
            self.stop(label)
        self._samples.clear()
        self._durations_ms.clear()


__all__ = ["TaskTimer"]
