# NPU Server Usage Reference

## Scope

This repo contains a standalone Ascend NPU task scheduler centered on `server/npu`.
Generic queue/scheduler/task-runner primitives live in `server/common`.

## Startup

Recommended startup:

```bash
cd /workspace
export NO_PROXY=127.0.0.1,localhost,::1
export no_proxy=127.0.0.1,localhost,::1
python -m server.npu.main --npu-config server/npu/configs/npu_resources/aicc-06_npu_config.yml
```

Alternative installed entrypoint:

```bash
npu-server --npu-config /workspace/server/npu/configs/npu_resources/aicc-06_npu_config.yml
```

Useful flags:

- `--host`: bind address, default `0.0.0.0`
- `--port`: bind port, default `8080`
- `--npu-config`: YAML config path
- `--npus`: explicit NPU ids to register
- `--npu-mode`: default mode for `--npus`
- `--memory-threshold`: default memory threshold for `--npus`
- `--lb-strategy`: `default`, `round_robin`, `least_loaded`, `fill`
- `--log-file`: custom session log path

## Default Device Selection

Behavior when `ASCEND_RT_VISIBLE_DEVICES` is unset:

- Server probes host NPUs with `npu-smi info`
- It selects the last 4 NPUs by default
- On this host, that resolves to `4,5,6,7`
- The same rule is used by `python -m server.npu.tools.npu_detect`

Generate a config from live hardware:

```bash
python -m server.npu.tools.npu_detect --dry-run --print-command
```

Generate all detected devices instead of the default last four:

```bash
python -m server.npu.tools.npu_detect --all --print-command
```

## Proxy and Loopback Notes

In this environment, loopback HTTP can be broken by inherited proxy variables.

Shell-side mitigation:

```bash
export NO_PROXY=127.0.0.1,localhost,::1
export no_proxy=127.0.0.1,localhost,::1
```

Client-side mitigation already exists in `server/npu/client.py`:

- If the base URL host is `127.0.0.1`, `localhost`, or `::1`
- The client disables proxy inheritance with `requests.Session().trust_env = False`

TypeScript callers should similarly pass `proxy: false` for axios or rely on direct loopback fetch without corporate proxy wrappers.

## Timezone Notes

`server/common/timezone.py` controls:

- log timestamps
- task submit/start/end timestamps
- timestamp-based log filenames

Normal behavior:

- Prefer Python `ZoneInfo`, which uses installed system timezone data
- Fall back to fixed offsets only if timezone data is unavailable

Current host status:

- `tzdata` is installed
- `ZoneInfo("UTC")` and `ZoneInfo("Asia/Shanghai")` both work directly

## Config Shape

Minimal NPU config:

```yaml
npus:
  - logical_id: 4
    npu_smi_id: 4
    visible_id: 4
    name: "910B1"
    enabled: true
    default_mode: "shared"
    memory_threshold: 1.0
    max_concurrent_tasks: 2

server:
  auto_register_npus: true
```

Fields:

- `logical_id`: server-visible NPU id
- `npu_smi_id`: index used when reading `npu-smi`
- `visible_id`: value exported to `ASCEND_RT_VISIBLE_DEVICES`
- `default_mode`: `shared` or `exclusive`
- `memory_threshold`: fraction between `0` and `1`
- `max_concurrent_tasks`: concurrency limit in shared mode

## Core API

### Health

```bash
curl -s http://127.0.0.1:8080/health
```

### List NPUs

```bash
curl -s http://127.0.0.1:8080/npus
```

### Get One NPU

```bash
curl -s http://127.0.0.1:8080/npus/4
```

### Set NPU Mode

```bash
curl -s -X PUT http://127.0.0.1:8080/npus/4/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"exclusive","manual":true}'
```

### Clear Manual Mode

```bash
curl -s -X DELETE http://127.0.0.1:8080/npus/4/mode
```

### Set Memory Threshold

```bash
curl -s -X PUT http://127.0.0.1:8080/npus/4/memory_threshold \
  -H 'Content-Type: application/json' \
  -d '{"threshold":0.95}'
```

### Set Max Concurrent Tasks

```bash
curl -s -X PUT http://127.0.0.1:8080/npus/4/max_concurrent_tasks \
  -H 'Content-Type: application/json' \
  -d '{"max_tasks":3}'
```

### Register and Unregister an NPU

```bash
curl -s -X POST http://127.0.0.1:8080/npus/register \
  -H 'Content-Type: application/json' \
  -d '{"npu_id":99,"mode":"shared","memory_threshold":1.0,"max_concurrent_tasks":1}'
```

```bash
curl -s -X POST http://127.0.0.1:8080/npus/99/unregister
```

### Submit a Task

```bash
curl -s -X POST http://127.0.0.1:8080/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "script_path": "/workspace/tests/fixtures/run_subprocess.py",
    "work_dir": "/tmp",
    "args": ["bash","-lc","echo hello"],
    "task_type": "functional",
    "npu_id": 4
  }'
```

Task payload fields:

- `script_path`: executable Python wrapper path
- `work_dir`: working directory
- `args`: argv for the script
- `env`: extra environment variables
- `task_mode`: `shared` or `exclusive`
- `task_type`: `functional`, `performance`, `both`
- `task_label`: optional business label
- `npu_id`: optional preferred device

### Query a Task

```bash
curl -s http://127.0.0.1:8080/tasks/<task_id>
```

### List Tasks

```bash
curl -s http://127.0.0.1:8080/tasks
curl -s 'http://127.0.0.1:8080/tasks?status=running'
```

### Cancel a Task

Regular cancel:

```bash
curl -s -X POST http://127.0.0.1:8080/tasks/<task_id>/cancel
```

Force-cancel a running task:

```bash
curl -s -X POST 'http://127.0.0.1:8080/tasks/<task_id>/cancel?force=true'
```

### Read Task Logs

Summary log:

```bash
curl -s 'http://127.0.0.1:8080/tasks/<task_id>/log?log_type=summary'
```

Stdout chunk:

```bash
curl -s 'http://127.0.0.1:8080/tasks/<task_id>/log?log_type=stdout&offset=0&limit=4096'
```

Stderr chunk:

```bash
curl -s 'http://127.0.0.1:8080/tasks/<task_id>/log?log_type=stderr&offset=0&limit=4096'
```

### Stats

```bash
curl -s http://127.0.0.1:8080/stats
```

## Python Usage

Use the built-in client:

```python
from server.npu.client import NPUClient

client = NPUClient("http://127.0.0.1:8080")

assert client.health_check()
npus = client.list_npus()
task_id = client.submit_task(
    script_path="/workspace/tests/fixtures/run_subprocess.py",
    work_dir="/tmp",
    args=["bash", "-lc", "echo hello from npu"],
    task_type="functional",
    npu_id=npus[0]["npu_id"],
)

task = client.get_task(task_id)
log = client.get_task_log(task_id, log_type="stdout")
stats = client.get_stats()
```

Direct `requests` usage:

```python
import requests

session = requests.Session()
session.trust_env = False
base = "http://127.0.0.1:8080"

health = session.get(f"{base}/health", timeout=5).json()
npus = session.get(f"{base}/npus", timeout=5).json()["npus"]
```

## TypeScript Usage

Example with native `fetch`:

```ts
type SubmitTaskRequest = {
  script_path: string;
  work_dir?: string;
  args?: string[];
  env?: Record<string, string>;
  task_mode?: "shared" | "exclusive";
  task_type?: "functional" | "performance" | "both";
  task_label?: string;
  npu_id?: number;
};

type TaskResponse = {
  task_id: string;
  status: string;
  npu_id: number | null;
  assigned_npu: number | null;
  log_file: string | null;
};

const baseUrl = "http://127.0.0.1:8080";

async function submitTask(body: SubmitTaskRequest): Promise<string> {
  const res = await fetch(`${baseUrl}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  const data = await res.json();
  return data.task_id as string;
}

async function getTask(taskId: string): Promise<TaskResponse> {
  const res = await fetch(`${baseUrl}/tasks/${taskId}`);
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return (await res.json()) as TaskResponse;
}
```

Example with axios:

```ts
import axios from "axios";

const api = axios.create({
  baseURL: "http://127.0.0.1:8080",
  proxy: false,
  timeout: 10000,
});

const { data: npus } = await api.get("/npus");
const { data: submit } = await api.post("/tasks", {
  script_path: "/workspace/tests/fixtures/run_subprocess.py",
  work_dir: "/tmp",
  args: ["bash", "-lc", "echo ts"],
  task_type: "functional",
  npu_id: npus.npus[0].npu_id,
});
```

## Logs

Server logs:

- `server/npu/logs/npu_server.log`
- `server/npu/logs/npu_server_<timestamp>.log`

Per-task logs:

- `server/npu/logs/tasks/<task_id>.log`
- `server/npu/logs/tasks/<task_id>.stdout`
- `server/npu/logs/tasks/<task_id>.stderr`

Use the API log endpoint first when debugging task output; fall back to direct file reads only when debugging file-rotation or encoding issues.

## Validation Commands

Unit and integration tests:

```bash
python -m unittest tests.test_timezone tests.test_npu_device_selection tests.test_npu_server_integration -v
```

Compile sanity:

```bash
python -m compileall /workspace/server/common /workspace/server/npu /workspace/tests
```

## `ops-samples` Validation

The environment was previously validated with:

- repo: `https://gitcode.com/guoxu7/ops-samples`
- sample: `Samples/0_Introduction/vector_add`

Environment checks:

- `ASCEND_HOME_PATH=/usr/local/Ascend/cann-8.5.0`
- `ASCEND_TOOLKIT_HOME=/usr/local/Ascend/cann-8.5.0`
- `bisheng` available under the Ascend toolkit

Practical note:

- The upstream sample used a hardcoded old arch flag in its `CMakeLists.txt`
- On this host, building succeeded after switching that compile flag to `Ascend910B1`

Typical validation flow:

1. Build the sample
2. Run it directly
3. Run it again through the NPU server using `tests/fixtures/run_subprocess.py`
4. Confirm task completion and stdout contains `Vector add completed successfully!`

## Operational Expectations

- Prefer loopback binds like `127.0.0.1:<port>` for local testing
- Keep `NO_PROXY` and `no_proxy` set for loopback calls in this environment
- Avoid reintroducing GPU compatibility payloads such as `gpu_id` or `assigned_gpu`
- Keep generic scheduler/runtime code in `server/common`
- Keep Ascend-specific behavior in `server/npu`
