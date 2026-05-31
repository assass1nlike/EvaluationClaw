"""Compatibility alias for evalclaw.prompts.generator."""
import sys as _sys

from .prompts import generator as _module

_sys.modules[__name__] = _module
