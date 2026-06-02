"""Compatibility alias for evalclaw.execution.agent_envs."""
import sys as _sys

from .execution import agent_envs as _module

_sys.modules[__name__] = _module
