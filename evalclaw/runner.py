"""Compatibility alias for evalclaw.execution.runner."""
import sys as _sys

from .execution import runner as _module

_sys.modules[__name__] = _module
