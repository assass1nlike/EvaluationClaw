"""Compatibility alias for evalclaw.generation.fallback."""
import sys as _sys

from .generation import fallback as _module

_sys.modules[__name__] = _module
