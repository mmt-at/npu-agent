"""Helpers for choosing which NPUs should be visible by default."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence

DEFAULT_LAST_NPU_COUNT = 4

_NPU_HEAD_LINE_RE = re.compile(r"^\|\s*(\d+)\s+([A-Za-z0-9._-]+)\s+\|")


def parse_npu_ids_from_npu_smi(output: str) -> list[int]:
    """Extract NPU ids from `npu-smi info` output."""
    ids: set[int] = set()
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if "No running processes found in NPU" in line:
            break
        match = _NPU_HEAD_LINE_RE.match(line)
        if match and "NPU" not in line and "Version" not in line:
            ids.add(int(match.group(1)))
    return sorted(ids)


def detect_host_npu_ids() -> list[int]:
    """Return NPU ids visible to the host, or an empty list if unavailable."""
    try:
        result = subprocess.run(
            ["npu-smi", "info"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return parse_npu_ids_from_npu_smi(result.stdout)


def parse_visible_device_ids(value: str | None) -> list[int] | None:
    """Parse ASCEND_RT_VISIBLE_DEVICES into integer ids."""
    if value is None:
        return None

    ids: list[int] = []
    for raw_token in value.split(","):
        token = raw_token.strip()
        if not token:
            continue
        try:
            ids.append(int(token))
        except ValueError:
            continue
    return ids or None


def select_default_npu_ids(npu_ids: Sequence[int], last_n: int = DEFAULT_LAST_NPU_COUNT) -> list[int]:
    """Select the last N NPU ids as the default active pool."""
    unique_ids = sorted({int(npu_id) for npu_id in npu_ids})
    if last_n <= 0 or len(unique_ids) <= last_n:
        return unique_ids
    return unique_ids[-last_n:]


def resolve_default_visible_device_ids(
    env_value: str | None = None,
    detected_npu_ids: Sequence[int] | None = None,
    last_n: int = DEFAULT_LAST_NPU_COUNT,
) -> list[int] | None:
    """Resolve the effective visible-device set.

    Explicit `ASCEND_RT_VISIBLE_DEVICES` wins. Otherwise, detect the host NPUs and
    keep only the last `last_n` devices by default.
    """
    explicit_ids = parse_visible_device_ids(env_value)
    if explicit_ids is not None:
        return explicit_ids

    host_npu_ids = list(detected_npu_ids) if detected_npu_ids is not None else detect_host_npu_ids()
    if not host_npu_ids:
        return None
    return select_default_npu_ids(host_npu_ids, last_n=last_n)
