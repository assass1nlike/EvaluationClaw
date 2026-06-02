"""Compatibility alias for evalclaw.execution.sandbox."""
import sys as _sys

from .execution import sandbox as _module

_sys.modules[__name__] = _module
