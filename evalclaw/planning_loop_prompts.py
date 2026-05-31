"""Compatibility alias for evalclaw.prompts.planning_loop."""
import sys as _sys

from .prompts import planning_loop as _module

_sys.modules[__name__] = _module
