"""Compatibility alias for evalclaw.planning.planner."""
import sys as _sys

from .planning import planner as _module

_sys.modules[__name__] = _module
