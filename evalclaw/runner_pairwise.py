"""Compatibility alias for evalclaw.runners.pairwise."""
import sys as _sys

from .runners import pairwise as _module

_sys.modules[__name__] = _module
