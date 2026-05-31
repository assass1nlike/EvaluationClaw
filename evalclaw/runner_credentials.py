"""Compatibility alias for evalclaw.runners.credentials."""
import sys as _sys

from .runners import credentials as _module

_sys.modules[__name__] = _module
