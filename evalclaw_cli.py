#!/usr/bin/env python3
"""Evalclaw CLI entry point.

Usage:
    python evalclaw_cli.py generate --goal "测试模型的谄媚行为"
    python evalclaw_cli.py generate -g "test complex code reasoning" -m claude-opus-4-6
    python evalclaw_cli.py generate --no-interactive --max-iterations 2
"""
from evalclaw.cli import main

if __name__ == "__main__":
    main()
