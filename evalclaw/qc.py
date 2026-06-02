"""Compatibility alias for evalclaw.quality.qc."""
import sys as _sys

from .quality import qc as _module

_sys.modules[__name__] = _module
