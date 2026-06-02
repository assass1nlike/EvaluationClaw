"""Compatibility alias for evalclaw.planning.loop."""
import sys as _sys

from .planning import loop as _module

_sys.modules[__name__] = _module
