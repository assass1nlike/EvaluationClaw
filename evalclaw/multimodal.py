"""Compatibility alias for evalclaw.protocols.multimodal."""
import sys as _sys

from .protocols import multimodal as _module

_sys.modules[__name__] = _module
