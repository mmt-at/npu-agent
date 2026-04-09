"""Generic subprocess-backed task runner."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from server.common.service_config import TaskStatus, config
from server.common.service_logger import setup_logger
from server.common.service_models import Task
from server.common.task_refs import format_task_ref
from server.common.timezone import now_timestamp
from server.common.timer import HostTimer, TimerSample, create_host_timer

logger = setup_logger("task_runner")


def _create_task_timer(task: Task) -> tuple[HostTimer, list[TimerSample]]:
    captured: list[TimerSample] = []

    def _report(sample: TimerSample) -> None:
        captured.append(sample)
        status = "err" if sample.error else "ok"
        logger.debug(
            "task=%s timer_label=%s, duration_ms=%12.3fms, status=%s",
            format_task_ref(task),
            sample.label,
            sample.duration_ms,
            status,
        )

    return create_host_timer(reporter=_report), captured


class SubprocessTaskRunner:
    """Executes tasks as local subprocesses."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir).resolve()
        self.running_processes: dict[str, subprocess.Popen] = {}
        self.lock = threading.RLock()

    def resource_label(self) -> str:
        return "resource"

    def prepare_environment(self, task: Task, resource_id: int, env: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        return env, {}

    def run_task(self, task: Task, resource_id: int) -> bool:
        stdout_file = None
        stderr_file = None
        stdout_path = None
        stderr_path = None
        task_ref_str = format_task_ref(task)
        script_abs_path = os.path.abspath(task.script_path)
        cmd = [sys.executable, script_abs_path] + task.args
        running_timer_started = False

        def append_error_message(message: str):
            if not message:
                return
            if task.error_message:
                if message not in task.error_message:
                    task.error_message = f"{task.error_message} | {message}"
            else:
                task.error_message = message

        try:
            task.status = TaskStatus.RUNNING
            task.assigned_resource = resource_id
            task.start_timestamp = now_timestamp()
            task.error_message = None

            queue_duration = task.timer.stop("queue")
            if queue_duration is not None:
                task.phase_duration_ms["queue"] = queue_duration
            waiting_duration = task.timer.stop("waiting")
            if waiting_duration is not None:
                task.phase_duration_ms["waiting"] = waiting_duration

            logger.info("Starting TASK %s on %s %s", task_ref_str, self.resource_label(), resource_id)
            logger.info("  Script: %s", script_abs_path)

            env = os.environ.copy()
            env, debug_env = self.prepare_environment(task, resource_id, env)
            if task.env:
                env.update(task.env)

            log_dir = self.root_dir / "logs" / "tasks"
            log_dir.mkdir(parents=True, exist_ok=True)
            task.log_file = str(log_dir / f"{task.task_id}.log")
            stdout_path = log_dir / f"{task.task_id}.stdout"
            stderr_path = log_dir / f"{task.task_id}.stderr"

            logger.debug("TASK %s command: %s", task_ref_str, " ".join(cmd))
            logger.debug("TASK %s work_dir: %s", task_ref_str, os.path.abspath(task.work_dir))
            for key, value in debug_env.items():
                logger.debug("TASK %s %s: %s", task_ref_str, key, value)

            stdout_file = open(stdout_path, "w", buffering=1)
            stderr_file = open(stderr_path, "w", buffering=1)

            process = subprocess.Popen(
                cmd,
                cwd=task.work_dir,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
            )

            task.timer.start("running")
            running_timer_started = True

            with self.lock:
                self.running_processes[task.task_id] = process

            timer, samples = _create_task_timer(task)
            try:
                with timer.time("task_runner.process_run"):
                    exit_code = process.wait(timeout=config.task_timeout)
            except subprocess.TimeoutExpired:
                logger.warning("TASK %s timed out, terminating...", task_ref_str, exc_info=True)
                process.kill()
                process.wait()
                raise
            finally:
                if samples:
                    task.execution_duration_ms = samples[-1].duration_ms
                with self.lock:
                    self.running_processes.pop(task.task_id, None)

            stdout_file.close()
            stderr_file.close()
            stdout_file = None
            stderr_file = None

            task.stdout_size = stdout_path.stat().st_size
            task.stderr_size = stderr_path.stat().st_size
            task.exit_code = exit_code
            task.end_timestamp = now_timestamp()

            if exit_code == 0:
                task.status = TaskStatus.COMPLETED
                logger.info("TASK %s completed successfully (exit_code=0)", task_ref_str)
            elif exit_code < 0:
                signal_name = self._get_signal_name(abs(exit_code))
                if task.status != TaskStatus.CANCELLED:
                    task.status = TaskStatus.FAILED
                    append_error_message(f"Process terminated by signal {signal_name} ({exit_code})")
                logger.error("TASK %s terminated by signal %s (%s)", task_ref_str, signal_name, exit_code)
            else:
                if task.status != TaskStatus.CANCELLED:
                    task.status = TaskStatus.FAILED
                    append_error_message(f"Exit code {exit_code}")
                logger.warning("TASK %s failed with exit code %s", task_ref_str, exit_code)

            self._write_log_file(task, script_abs_path, cmd, stdout_path, stderr_path)
            return True

        except subprocess.TimeoutExpired:
            task.status = TaskStatus.FAILED
            append_error_message(f"Timeout after {config.task_timeout} seconds")
            task.end_timestamp = now_timestamp()
            logger.error("TASK %s timed out after %ss", task_ref_str, config.task_timeout, exc_info=True)
            if stdout_file:
                stdout_file.close()
            if stderr_file:
                stderr_file.close()
            try:
                if stdout_path and stdout_path.exists():
                    task.stdout_size = stdout_path.stat().st_size
                if stderr_path and stderr_path.exists():
                    task.stderr_size = stderr_path.stat().st_size
            except Exception:
                pass
            self._write_log_file(task, script_abs_path, cmd, stdout_path, stderr_path, timeout=True)
            return True

        except Exception as exc:
            task.status = TaskStatus.FAILED
            append_error_message(str(exc))
            task.end_timestamp = now_timestamp()
            logger.error("TASK %s failed with exception: %s", task_ref_str, exc, exc_info=True)
            if stdout_file:
                stdout_file.close()
            if stderr_file:
                stderr_file.close()
            try:
                if stdout_path and stdout_path.exists():
                    task.stdout_size = stdout_path.stat().st_size
                if stderr_path and stderr_path.exists():
                    task.stderr_size = stderr_path.stat().st_size
            except Exception:
                pass
            self._write_log_file(task, script_abs_path, cmd, stdout_path, stderr_path, exception=str(exc))
            return False
        finally:
            if running_timer_started:
                running_duration = task.timer.stop("running")
                if running_duration is not None:
                    task.phase_duration_ms["running"] = running_duration
            total_duration = task.timer.stop("total")
            if total_duration is not None:
                task.phase_duration_ms["total"] = total_duration

    def _get_signal_name(self, signum: int) -> str:
        signal_names = {
            1: "SIGHUP",
            2: "SIGINT",
            3: "SIGQUIT",
            4: "SIGILL",
            6: "SIGABRT",
            7: "SIGBUS",
            8: "SIGFPE",
            9: "SIGKILL",
            11: "SIGSEGV",
            13: "SIGPIPE",
            14: "SIGALRM",
            15: "SIGTERM",
        }
        return signal_names.get(signum, f"SIG{signum}")

    def _write_log_file(
        self,
        task: Task,
        script_abs_path: str,
        cmd: list[str],
        stdout_path: Path | None,
        stderr_path: Path | None,
        timeout: bool = False,
        exception: str | None = None,
    ):
        if not task.log_file or stdout_path is None or stderr_path is None:
            return

        try:
            task_ref = format_task_ref(task)
            with open(task.log_file, "w", encoding="utf-8") as handle:
                handle.write(f"=== Task {task.task_id} ===\n")
                handle.write(f"Mode: {task.task_mode.value}\n")
                if task.task_type:
                    handle.write(f"Type: {task.task_type.value}\n")
                if task.task_label:
                    handle.write(f"Label: {task.task_label}\n")
                handle.write(f"Script: {script_abs_path}\n")
                handle.write(f"Work Dir: {os.path.abspath(task.work_dir)}\n")
                handle.write(f"{self.resource_label().upper()}: {task.assigned_resource}\n")
                handle.write(f"Command: {' '.join(cmd)}\n")
                handle.write("\n=== Timing ===\n")
                handle.write(f"Submit Timestamp:  {task.submit_timestamp}\n")
                if task.queued_timestamp:
                    handle.write(f"Queued Timestamp:  {task.queued_timestamp}\n")
                if task.start_timestamp:
                    handle.write(f"Start Timestamp:   {task.start_timestamp}\n")
                if task.end_timestamp:
                    handle.write(f"End Timestamp:     {task.end_timestamp}\n")

                handle.write("\n=== Timing Breakdown (ms) ===\n")
                duration_width = 15

                def _fmt_duration(value: float) -> str:
                    return f"{value:>{duration_width},.2f}"

                if task.pending_duration_ms is not None:
                    handle.write(f"Pending Duration:     {_fmt_duration(task.pending_duration_ms)} ms\n")
                if task.queue_duration_ms is not None:
                    handle.write(f"Queue Duration:       {_fmt_duration(task.queue_duration_ms)} ms\n")
                if task.waiting_duration_ms is not None:
                    handle.write(f"Waiting Duration:     {_fmt_duration(task.waiting_duration_ms)} ms\n")
                if task.running_duration_ms is not None:
                    handle.write(f"Running Duration:     {_fmt_duration(task.running_duration_ms)} ms\n")
                if task.total_duration_ms is not None:
                    handle.write(f"Total Duration:       {_fmt_duration(task.total_duration_ms)} ms\n")
                if task.execution_duration_ms:
                    handle.write("\n=== Execution Duration (ms) ===\n")
                    handle.write(f"Process Running Duration: {_fmt_duration(task.execution_duration_ms)} ms\n")

                handle.write("\n=== Result ===\n")
                if timeout:
                    handle.write("Status: TIMEOUT\n")
                    handle.write(f"ERROR: Task timed out after {config.task_timeout} seconds\n")
                elif exception:
                    handle.write("Status: EXCEPTION\n")
                    handle.write(f"ERROR: Exception occurred: {exception}\n")
                else:
                    handle.write(f"Status: {task.status.value}\n")
                    handle.write(f"Exit Code: {task.exit_code}\n")
                    if task.exit_code and task.exit_code < 0:
                        signal_name = self._get_signal_name(abs(task.exit_code))
                        handle.write(f"Signal: {signal_name}\n")
                        handle.write("Note: Process was terminated by signal\n")

                handle.write("\n=== Output Files ===\n")
                handle.write(f"STDOUT: {stdout_path} ({self._format_size(task.stdout_size)})\n")
                handle.write(f"STDERR: {stderr_path} ({self._format_size(task.stderr_size)})\n")

                if task.stdout_size > 0:
                    handle.write("\n=== STDOUT Preview ===\n")
                    if task.stdout_size < 10240:
                        with open(stdout_path, "r", encoding="utf-8", errors="replace") as stdout_handle:
                            handle.write(stdout_handle.read())
                    else:
                        with open(stdout_path, "r", encoding="utf-8", errors="replace") as stdout_handle:
                            preview = stdout_handle.read(5120)
                            handle.write(preview)
                            handle.write(
                                f"\n\n... (truncated, {self._format_size(task.stdout_size - 5120)} remaining)\n"
                            )
                            handle.write(f"See full output in: {stdout_path}\n")
                else:
                    handle.write("\n=== STDOUT ===\n(empty)\n")

                if task.stderr_size > 0:
                    handle.write("\n=== STDERR Preview ===\n")
                    if task.stderr_size < 10240:
                        with open(stderr_path, "r", encoding="utf-8", errors="replace") as stderr_handle:
                            handle.write(stderr_handle.read())
                    else:
                        with open(stderr_path, "r", encoding="utf-8", errors="replace") as stderr_handle:
                            preview = stderr_handle.read(5120)
                            handle.write(preview)
                            handle.write(
                                f"\n\n... (truncated, {self._format_size(task.stderr_size - 5120)} remaining)\n"
                            )
                            handle.write(f"See full output in: {stderr_path}\n")
                else:
                    handle.write("\n=== STDERR ===\n(empty)\n")

                handle.write("\n=== END OF LOG ===\n")
            logger.debug("TASK %s log written to %s", task_ref, task.log_file)
        except Exception as exc:
            logger.error("Failed to write log file for task %s: %s", task_ref, exc, exc_info=True)

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes}B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"

    def kill_task(self, task: Task) -> bool:
        with self.lock:
            process = self.running_processes.get(task.task_id)
            if not process:
                logger.warning("Cannot kill TASK %s: not running or already finished", format_task_ref(task))
                return False
            try:
                logger.info("Terminating TASK %s...", format_task_ref(task))
                process.terminate()
                try:
                    process.wait(timeout=5)
                    logger.info("TASK %s terminated gracefully", format_task_ref(task))
                except subprocess.TimeoutExpired:
                    logger.warning("TASK %s did not terminate, sending SIGKILL...", format_task_ref(task), exc_info=True)
                    process.kill()
                    process.wait()
                    logger.info("TASK %s killed forcefully", format_task_ref(task), exc_info=True)
                return True
            except Exception as exc:
                logger.error("Failed to kill TASK %s: %s", format_task_ref(task), exc, exc_info=True)
                return False


__all__ = ["SubprocessTaskRunner"]
