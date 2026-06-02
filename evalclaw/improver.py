"""Compatibility alias for evalclaw.quality.improver."""
import sys as _sys

from .quality import improver as _module

_sys.modules[__name__] = _module
