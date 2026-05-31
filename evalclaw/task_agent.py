"""Compatibility alias for evalclaw.protocols.task_agent."""
import sys as _sys

from .protocols import task_agent as _module

_sys.modules[__name__] = _module
