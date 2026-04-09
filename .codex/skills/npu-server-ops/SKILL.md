---
name: npu-server-ops
description: Use when working on this repository's Ascend NPU task-scheduling server, including startup, configuration, curl/API usage, Python client usage, TypeScript integration, logging, proxy handling, and validation with local NPU hardware.
---

# NPU Server Ops

Use this skill when the task involves the standalone NPU server under `server/npu`.

## Quick Workflow

1. Read `references/usage.md` for the exact startup mode, environment variables, and API contracts.
2. Default to the NPU config at `server/npu/configs/npu_resources/aicc-06_npu_config.yml` unless the task clearly needs another config.
3. Assume loopback requests may be intercepted by proxies in this environment.
   Set `NO_PROXY=127.0.0.1,localhost,::1` and `no_proxy=127.0.0.1,localhost,::1` for shell-based tests.
4. If `ASCEND_RT_VISIBLE_DEVICES` is unset, the server defaults to the last 4 detected NPUs.
   On this host that means `4,5,6,7`.
5. Prefer the repo's Python client for scripted checks; use raw `curl` or `fetch` only when the task is specifically about HTTP integration.

## What Is Generic vs NPU-Specific

- Generic scheduling/runtime pieces live under `server/common`.
- Ascend-specific monitoring, NPU config loading, and `ASCEND_RT_VISIBLE_DEVICES` handling live under `server/npu`.
- Do not reintroduce `server/nvgpu`; that codepath was intentionally removed from this repo.

## Read This Reference

- Full operational reference: `references/usage.md`

## Validation Expectations

- For basic code changes, run:
  `python -m unittest tests.test_timezone tests.test_npu_device_selection tests.test_npu_server_integration -v`
- For startup/config validation, run:
  `python -m server.npu.tools.npu_detect --dry-run --print-command`
- When validating real runtime execution, prefer a loopback bind such as `127.0.0.1:<port>` and verify `/health`, `/npus`, task submit, task log, and cancel paths.
