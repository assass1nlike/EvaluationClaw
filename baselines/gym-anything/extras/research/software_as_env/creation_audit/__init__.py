"""Creation–Audit loop for converting software into gym-anything environments.

See `method.py` for the entry point. This is part of `gym-anything-extras`
(research category). Not part of the gym-anything library proper.
"""

from .method import build_parser, run, run_creation_audit

__all__ = ["build_parser", "run", "run_creation_audit"]
