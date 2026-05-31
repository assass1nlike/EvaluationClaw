"""Compatibility alias for evalclaw.runners.agent."""
import sys as _sys

from .runners import agent as _module

_sys.modules[__name__] = _module
