"""Compatibility alias for evalclaw.reporting.viewer."""
import sys as _sys

from .reporting import viewer as _module

_sys.modules[__name__] = _module
