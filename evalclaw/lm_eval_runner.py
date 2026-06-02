"""Compatibility alias for evalclaw.execution.lm_eval."""
import sys as _sys

from .execution import lm_eval as _module

_sys.modules[__name__] = _module
