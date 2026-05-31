"""Compatibility alias for evalclaw.protocols.tool_adapters."""
import sys as _sys

from .protocols import tool_adapters as _module

_sys.modules[__name__] = _module
