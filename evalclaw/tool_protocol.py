"""Compatibility alias for evalclaw.protocols.tool."""
import sys as _sys

from .protocols import tool as _module

_sys.modules[__name__] = _module
