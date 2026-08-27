"""EvaluationClaw live run visualisation server.

Start with ``evalclaw serve`` (keeps running) or the server auto-starts on
the first ``evalclaw generate --live`` invocation.

Public surface used by the rest of the framework::

    from evalclaw.live import get_streamer, register_run, notify_stage, notify_log

All operations are no-ops when the server is not running (``enabled=False``).
"""
from .registry import get_run, register_run
from .server import is_running, server_url, start_server
from .streamers import get_streamer, notify_log, notify_stage

__all__ = [
    "register_run",
    "get_run",
    "get_streamer",
    "notify_stage",
    "notify_log",
    "start_server",
    "server_url",
    "is_running",
]
