"""Compatibility alias for evalclaw.reporting.artifacts."""
import sys as _sys

from .reporting import artifacts as _module

_sys.modules[__name__] = _module
