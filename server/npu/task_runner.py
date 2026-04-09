"""Task runner for executing scripts on NPU."""

from __future__ import annotations

from pathlib import Path

from server.common.subprocess_task_runner import SubprocessTaskRunner
from server.common.service_models import Task
from server.npu.logger import setup_logger

logger = setup_logger("task_runner")

npu_config_loader = None


class TaskRunner(SubprocessTaskRunner):
    """Ascend-aware task runner."""

    def __init__(self):
        super().__init__(root_dir=Path(__file__).parent.resolve())

    def resource_label(self) -> str:
        return "NPU"

    def prepare_environment(
        self,
        task: Task,
        resource_id: int,
        env: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        visible_id = resource_id
        if npu_config_loader:
            mapped_id = npu_config_loader.get_visible_id(resource_id)
            if mapped_id is not None:
                visible_id = mapped_id

        if not task.env or "ASCEND_RT_VISIBLE_DEVICES" not in task.env:
            env["ASCEND_RT_VISIBLE_DEVICES"] = str(visible_id)

        return env, {"ASCEND_RT_VISIBLE_DEVICES": str(visible_id)}
