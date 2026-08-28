"""EvaluationClaw live run visualisation server.

Start with ``evalclaw serve`` and run one or more ``evalclaw generate --live``
clients against it.

Public surface used by the rest of the framework::

    from evalclaw.live import get_streamer, register_run, notify_stage, notify_log

Local streamers are no-ops when no run is registered; remote runs publish to
the configured live server over HTTP.
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
