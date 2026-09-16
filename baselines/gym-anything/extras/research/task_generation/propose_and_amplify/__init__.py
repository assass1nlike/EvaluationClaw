"""Propose-and-Amplify task generation (CUA-World §4).

`method.py` exposes the user-facing CLI. `pipeline/` holds the underlying
stage implementations.
"""

from .method import build_parser, run

__all__ = ["build_parser", "run"]
