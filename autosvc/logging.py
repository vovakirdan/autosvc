from __future__ import annotations

import contextlib
import contextvars
import datetime as _dt
import json
import logging
import os
import sys
import traceback
from typing import Any

# Custom TRACE level (more verbose than DEBUG).
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _logger_trace(self: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


if not hasattr(logging.Logger, "trace"):
    logging.Logger.trace = _logger_trace  # type: ignore[attr-defined]


_trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("autosvc_trace_id", default=None)


@contextlib.contextmanager
def trace_context(trace_id: str) -> Any:
    token = _trace_id_var.set(str(trace_id))
    try:
        yield
    finally:
        _trace_id_var.reset(token)


def get_trace_id() -> str | None:
    return _trace_id_var.get()


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 (filter)
        # Make sure these always exist for formatting.
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()  # type: ignore[attr-defined]
        return True


_RESERVED_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
}


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in record.__dict__.items():
        if k in _RESERVED_ATTRS:
            continue
        if k.startswith("_"):
            continue
        out[k] = v
    return out


class PrettyFormatter(logging.Formatter):
    def __init__(self, *, use_color: bool) -> None:
        super().__init__()
        self._use_color = bool(use_color)

    def format(self, record: logging.LogRecord) -> str:
        ts = _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")
        level = record.levelname
        logger = record.name
        msg = record.getMessage()

        parts = [ts, level, logger, msg]

        extras = _record_extras(record)
        # Put trace_id near the front if present.
        trace_id = extras.pop("trace_id", None)
        if trace_id:
            parts.append(f"trace_id={trace_id}")
        for k in sorted(extras.keys()):
            v = extras[k]
            parts.append(f"{k}={v}")

        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        if self._use_color:
            line = _colorize(record.levelno, line)
        return line


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc).astimezone().isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extras = _record_extras(record)
        payload.update(extras)
        if record.exc_info:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _colorize(levelno: int, text: str) -> str:
    # ANSI colors: keep simple and readable.
    if levelno >= logging.ERROR:
        color = "31"  # red
    elif levelno >= logging.WARNING:
        color = "33"  # yellow
    elif levelno >= logging.INFO:
        color = "32"  # green
    elif levelno >= logging.DEBUG:
        color = "36"  # cyan
    else:
        color = "90"  # bright black / gray
    return f"\x1b[{color}m{text}\x1b[0m"


def parse_log_level(value: str | None) -> int:
    raw = (value or "").strip().lower()
    if not raw or raw == "info":
        return logging.INFO
    if raw == "error":
        return logging.ERROR
    if raw == "warning" or raw == "warn":
        return logging.WARNING
    if raw == "debug":
        return logging.DEBUG
    if raw == "trace":
        return TRACE_LEVEL
    raise ValueError("invalid log level")


def setup_logging(
    *,
    level: int = logging.INFO,
    log_format: str = "pretty",
    log_file: str | None = None,
    no_color: bool = False,
) -> None:
    """Configure root logging.

    - Logs go to stderr by default.
    - Optionally also log to a file.
    - Stdout is reserved for command results (JSON outputs).
    """

    fmt = (log_format or "pretty").strip().lower()
    if fmt not in {"pretty", "json"}:
        raise ValueError("invalid log format")

    use_color = (not no_color) and bool(getattr(sys.stderr, "isatty", lambda: False)())

    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
        file_formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = PrettyFormatter(use_color=use_color)
        file_formatter = PrettyFormatter(use_color=False)

    handlers: list[logging.Handler] = []

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(_ContextFilter())
    handlers.append(stderr_handler)

    if log_file:
        path = os.path.expanduser(str(log_file))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(file_formatter)
        fh.addFilter(_ContextFilter())
        handlers.append(fh)

    logging.basicConfig(level=int(level), handlers=handlers, force=True)

    # Make third-party libraries quieter by default.
    # Keep autosvc INFO logs visible, but avoid python-can INFO noise unless debugging.
    third_party_level = logging.WARNING
    if int(level) <= TRACE_LEVEL or int(level) <= logging.DEBUG:
        third_party_level = logging.DEBUG
    logging.getLogger("can").setLevel(int(third_party_level))
