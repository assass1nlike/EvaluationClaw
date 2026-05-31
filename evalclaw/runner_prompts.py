"""Compatibility alias for evalclaw.runners.prompts."""
import sys as _sys

from .runners import prompts as _module

_sys.modules[__name__] = _module
