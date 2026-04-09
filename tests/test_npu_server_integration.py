import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import requests

from server.npu.client import NPUClient
from server.npu.device_selection import detect_host_npu_ids, select_default_npu_ids

ROOT = Path(__file__).resolve().parents[1]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(base_url: str, session: requests.Session, proc: subprocess.Popen, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            output = ""
            if proc.stdout:
                output = proc.stdout.read()
            raise RuntimeError(f"Server exited early with code {proc.returncode}:\n{output}")
        try:
            response = session.get(f"{base_url}/health", timeout=1)
            if response.status_code == 200:
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise TimeoutError(f"Server did not become healthy: {base_url}")


@unittest.skipUnless(len(detect_host_npu_ids()) >= 4, "requires at least 4 detectable NPUs")
class NPUServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.detected_ids = detect_host_npu_ids()
        self.expected_ids = select_default_npu_ids(self.detected_ids)
        self.port = _find_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmpdir.name)
        self.config_path = self.workdir / "all_npus.yml"
        self._write_config()

        env = os.environ.copy()
        env.pop("ASCEND_RT_VISIBLE_DEVICES", None)
        env["PYTHONPATH"] = str(ROOT) + (f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else "")
        env["NO_PROXY"] = "127.0.0.1,localhost,::1"
        env["no_proxy"] = env["NO_PROXY"]

        self.session = requests.Session()
        self.session.trust_env = False
        self.client = NPUClient(self.base_url)

        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "server.npu.main",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--npu-config",
                str(self.config_path),
                "--log-level",
                "INFO",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_for_server(self.base_url, self.session, self.proc)

    def tearDown(self):
        if hasattr(self, "proc") and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        if hasattr(self, "proc") and self.proc.stdout:
            self.proc.stdout.close()
        if hasattr(self, "session"):
            self.session.close()
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def _write_config(self) -> None:
        lines = ["npus:"]
        for npu_id in self.detected_ids:
            lines.extend(
                [
                    f"  - logical_id: {npu_id}",
                    f"    npu_smi_id: {npu_id}",
                    f"    visible_id: {npu_id}",
                    '    name: "Ascend 910B1"',
                    "    enabled: true",
                    '    default_mode: "shared"',
                    "    memory_threshold: 1.0",
                    "    max_concurrent_tasks: 2",
                    "",
                ]
            )
        lines.extend(["server:", "  auto_register_npus: true", ""])
        self.config_path.write_text("\n".join(lines), encoding="utf-8")

    def _wait_for_task(self, task_id: str, terminal_statuses: set[str], timeout_s: float = 30.0) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            response = self.session.get(f"{self.base_url}/tasks/{task_id}", timeout=3)
            response.raise_for_status()
            payload = response.json()
            if payload["status"] in terminal_statuses:
                return payload
            time.sleep(0.5)
        raise TimeoutError(f"Task {task_id} did not reach terminal state")

    def test_server_end_to_end(self):
        self.assertTrue(self.client.health_check())
        npus_response = self.session.get(f"{self.base_url}/npus", timeout=5)
        npus_response.raise_for_status()
        npus = npus_response.json()["npus"]
        self.assertEqual([item["npu_id"] for item in npus], self.expected_ids)
        self.assertEqual([item["npu_id"] for item in self.client.list_npus()], self.expected_ids)

        first_npu = self.expected_ids[0]
        second_npu = self.expected_ids[1]

        get_npu_response = self.session.get(f"{self.base_url}/npus/{first_npu}", timeout=5)
        get_npu_response.raise_for_status()
        self.assertEqual(get_npu_response.json()["npu_id"], first_npu)
        self.assertEqual(self.client.get_npu(first_npu)["npu_id"], first_npu)

        response = self.session.put(
            f"{self.base_url}/npus/{first_npu}/mode",
            json={"mode": "exclusive", "manual": True},
            timeout=5,
        )
        response.raise_for_status()
        response = self.session.delete(f"{self.base_url}/npus/{first_npu}/mode", timeout=5)
        response.raise_for_status()

        response = self.session.put(
            f"{self.base_url}/npus/{first_npu}/memory_threshold",
            json={"threshold": 0.95},
            timeout=5,
        )
        response.raise_for_status()
        response = self.session.put(
            f"{self.base_url}/npus/{first_npu}/max_concurrent_tasks",
            json={"max_tasks": 3},
            timeout=5,
        )
        response.raise_for_status()

        response = self.session.post(
            f"{self.base_url}/npus/register",
            json={"npu_id": 99, "mode": "shared", "memory_threshold": 1.0, "max_concurrent_tasks": 1},
            timeout=5,
        )
        response.raise_for_status()
        response = self.session.post(f"{self.base_url}/npus/99/unregister", timeout=5)
        response.raise_for_status()

        env_script = self.workdir / "print_env.py"
        env_script.write_text(
            textwrap.dedent(
                """
                import os
                print("ASCEND_RT_VISIBLE_DEVICES=" + os.environ.get("ASCEND_RT_VISIBLE_DEVICES", ""))
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        task_id = self.client.submit_task(
            script_path=str(env_script),
            work_dir=str(self.workdir),
            task_type="functional",
            npu_id=first_npu,
        )
        task_payload = self._wait_for_task(task_id, {"completed", "failed"})
        self.assertEqual(task_payload["status"], "completed")
        self.assertEqual(task_payload["assigned_npu"], first_npu)
        self.assertEqual(self.client.get_task(task_id).status, "completed")

        log_response = self.session.get(
            f"{self.base_url}/tasks/{task_id}/log",
            params={"log_type": "stdout"},
            timeout=5,
        )
        log_response.raise_for_status()
        self.assertIn(f"ASCEND_RT_VISIBLE_DEVICES={first_npu}", log_response.json()["content"])

        sleep_script = self.workdir / "sleep_task.py"
        sleep_script.write_text(
            textwrap.dedent(
                """
                import time
                time.sleep(30)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        cancel_task_id = self.client.submit_task(
            script_path=str(sleep_script),
            work_dir=str(self.workdir),
            task_mode="exclusive",
            npu_id=second_npu,
        )

        deadline = time.time() + 20
        while time.time() < deadline:
            payload = self.session.get(f"{self.base_url}/tasks/{cancel_task_id}", timeout=5).json()
            if payload["status"] == "running":
                break
            time.sleep(0.5)
        else:
            self.fail("Task never reached running state before cancel")

        self.assertTrue(self.client.cancel_task(cancel_task_id, force=True))
        cancelled_payload = self._wait_for_task(cancel_task_id, {"cancelled", "failed"})
        self.assertEqual(cancelled_payload["status"], "cancelled")

        stats_payload = self.client.get_stats()
        self.assertEqual(stats_payload["npus"]["total_npus"], len(self.expected_ids))


if __name__ == "__main__":
    unittest.main()
