#!/usr/bin/env python3
"""Run an arbitrary subprocess and mirror its output."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_subprocess.py <command> [args...]", file=sys.stderr)
        return 2

    result = subprocess.run(sys.argv[1:], text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
