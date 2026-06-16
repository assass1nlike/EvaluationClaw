"""Compatibility alias for evalclaw.protocols.science."""
from __future__ import annotations

from .protocols import science as _module
from .protocols.science import *  # noqa: F403

__all__ = getattr(_module, "__all__", [name for name in dir(_module) if not name.startswith("_")])
