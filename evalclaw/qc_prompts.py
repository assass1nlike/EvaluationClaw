"""Compatibility alias for evalclaw.prompts.qc."""
import sys as _sys

from .prompts import qc as _module

_sys.modules[__name__] = _module
