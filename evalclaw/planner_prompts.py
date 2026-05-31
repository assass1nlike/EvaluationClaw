"""Compatibility alias for evalclaw.prompts.planner."""
import sys as _sys

from .prompts import planner as _module

_sys.modules[__name__] = _module
