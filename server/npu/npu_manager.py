"""NPU manager for monitoring and managing NPU resources."""

from __future__ import annotations

import re
import shutil
import subprocess

from server.common.resource_manager import ResourceManager
from server.common.service_config import ResourceMode, ResourceStatus, TaskMode
from server.common.service_models import Task
from server.npu.logger import setup_logger

logger = setup_logger("npu_manager")

npu_config_loader = None


class NPUManager(ResourceManager):
    """Ascend/CANN-specific resource manager."""

    def resource_label(self) -> str:
        return "npu"

    def device_error_keywords(self) -> tuple[str, ...]:
        return (
            "npu error",
            "acl error",
            "ascend error",
            "aicore exception",
            "out of memory",
            "hbm",
        )

    def _initialize_monitor(self):
        self.npu_smi_available = shutil.which("npu-smi") is not None
        if not self.npu_smi_available:
            logger.warning("npu-smi not available, NPU memory monitoring disabled")
            self.monitor_initialized = False
            self.monitor_device_count = 0
            return

        self.monitor_initialized = True
        self.monitor_device_count = self._detect_npu_count()
        logger.info("npu-smi detected, found %d NPUs", self.monitor_device_count)

    def _detect_npu_count(self) -> int:
        output = self._run_npu_smi_info()
        if not output:
            return 0

        npu_ids: set[int] = set()
        line_pattern = re.compile(r"^\|\s*(\d+)\s+\S+\s+\|\s*\S+", re.MULTILINE)
        for match in line_pattern.finditer(output):
            npu_ids.add(int(match.group(1)))
        return len(npu_ids)

    def _run_npu_smi_info(self) -> str:
        try:
            result = subprocess.run(
                ["npu-smi", "info"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except Exception as exc:
            logger.debug("Failed to execute npu-smi info: %s", exc)
            return ""

    def _parse_hbm_usage(self, output: str) -> dict[int, float]:
        usage_by_id: dict[int, float] = {}
        current_npu_id: int | None = None

        head_line_re = re.compile(r"^\|\s*(\d+)\s+\S+\s+\|")
        fraction_re = re.compile(r"(\d+)\s*/\s*(\d+)")
        bus_id_re = re.compile(r"[0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-9]")

        for line in output.splitlines():
            head_match = head_line_re.match(line)
            if head_match:
                current_npu_id = int(head_match.group(1))
                continue

            if current_npu_id is None or not line.lstrip().startswith("|"):
                continue

            if not bus_id_re.search(line):
                continue

            pairs = fraction_re.findall(line)
            if not pairs:
                continue

            used_str, total_str = pairs[-1]
            total = int(total_str)
            used = int(used_str)
            if total > 0:
                usage_by_id[current_npu_id] = used / total
            current_npu_id = None

        return usage_by_id

    def _update_resource_memory(self, resource_id: int):
        if not self.monitor_initialized:
            return

        output = self._run_npu_smi_info()
        if not output:
            return

        usage_by_smi_id = self._parse_hbm_usage(output)
        npu_smi_id = resource_id
        if npu_config_loader:
            mapped_id = npu_config_loader.get_npu_smi_id(resource_id)
            if mapped_id is not None:
                npu_smi_id = mapped_id

        usage = usage_by_smi_id.get(npu_smi_id)
        if usage is None:
            return

        with self.lock:
            if resource_id in self.resources:
                self.resources[resource_id].current_memory_usage = usage

    def register_npu(
        self,
        npu_id: int,
        mode: ResourceMode | None = None,
        memory_threshold: float | None = None,
        max_concurrent_tasks: int | None = None,
    ) -> bool:
        return self.register_resource(
            resource_id=npu_id,
            mode=mode,
            memory_threshold=memory_threshold,
            max_concurrent_tasks=max_concurrent_tasks,
        )

    def unregister_npu(self, npu_id: int) -> bool:
        return self.unregister_resource(npu_id)

    def list_npus(self):
        return self.list_resources()

    def get_npu(self, npu_id: int):
        return self.get_resource(npu_id)

    def set_npu_status(self, npu_id: int, status: ResourceStatus) -> bool:
        return self.set_resource_status(npu_id, status)

    def set_npu_mode(self, npu_id: int, mode: ResourceMode, manual: bool = True) -> bool:
        return self.set_resource_mode(npu_id, mode, manual=manual)

    def clear_npu_manual_mode(self, npu_id: int) -> bool:
        return self.clear_manual_mode(npu_id)

    def set_npu_memory_threshold(self, npu_id: int, threshold: float) -> bool:
        return self.set_resource_memory_threshold(npu_id, threshold)

    def set_npu_max_concurrent_tasks(self, npu_id: int, max_tasks: int) -> bool:
        return self.set_resource_max_concurrent_tasks(npu_id, max_tasks)

    def find_available_npu(self, preferred_npu: int | None = None, task_mode: TaskMode | None = None):
        return self.find_available_resource(preferred_npu, task_mode)

    def set_npu_mode_for_task(self, npu_id: int, task: Task, task_mode_override: TaskMode | None = None) -> bool:
        return self.set_resource_mode_for_task(npu_id, task, task_mode_override)

    def restore_npu_mode_after_task(self, npu_id: int, task: Task) -> bool:
        return self.restore_resource_mode_after_task(npu_id, task)

    def mark_task_running_on_npu(self, npu_id: int, task: Task) -> bool:
        return self.mark_task_running(npu_id, task)

    def mark_task_completed_on_npu(self, npu_id: int, task: Task) -> bool:
        return self.mark_task_completed(npu_id, task)

    def list_paused_npus(self) -> list[int]:
        return self.list_paused_resources()

    def shutdown(self):
        self.stop_monitoring()
        logger.info("NPU manager shutdown completed")
