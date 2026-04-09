#!/usr/bin/env python3
"""CLI entry point for NPU server."""
from server.npu.main import main as _main


def cli_main():
    """Entry point for npu-server command."""
    _main()


if __name__ == "__main__":
    cli_main()
