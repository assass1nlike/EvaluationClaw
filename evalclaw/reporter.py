"""Compatibility alias for evalclaw.reporting.reporter."""
import sys as _sys

from .reporting import reporter as _module

_sys.modules[__name__] = _module
