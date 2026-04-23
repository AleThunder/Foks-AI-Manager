from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextvars import Token
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")
TASK_ID_CTX: ContextVar[str] = ContextVar("task_id", default="-")
MAX_LOG_FILE_SIZE = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5

_SKIP_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class ContextFilter(logging.Filter):
    """Inject request/task context values into every emitted log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Populate the record with current context ids before formatting."""
        record.request_id = REQUEST_ID_CTX.get()
        record.task_id = TASK_ID_CTX.get()
        return True


class JsonFormatter(logging.Formatter):
    """Render log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record into a compact JSON payload suitable for files and stdout."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", REQUEST_ID_CTX.get()),
            "task_id": getattr(record, "task_id", TASK_ID_CTX.get()),
        }

        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _SKIP_KEYS or key in payload:
                continue

            # Keep the output JSON-friendly even when callers pass richer Python objects in `extra=...`.
            payload[key] = value if isinstance(value, (str, int, float, bool, list, dict, type(None))) else str(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level: int = logging.INFO,
    *,
    log_dir: str | Path = "logs",
    force: bool = False,
) -> None:
    """Configure console and file logging handlers for the whole application."""
    if getattr(configure_logging, "_configured", False) and not force:
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    _clear_logger_handlers(root_logger)
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    console_handler = _build_handler(logging.StreamHandler())
    app_file_handler = _build_handler(
        RotatingFileHandler(
            log_path / "app.log",
            maxBytes=MAX_LOG_FILE_SIZE,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    )
    root_logger.addHandler(console_handler)
    root_logger.addHandler(app_file_handler)

    _reset_application_loggers()

    integration_logger = logging.getLogger("app.integration.foks")
    _clear_logger_handlers(integration_logger)
    integration_logger.handlers.clear()
    integration_logger.setLevel(level)
    integration_logger.propagate = True
    integration_logger.addHandler(
        _build_handler(
            RotatingFileHandler(
                log_path / "foks-integration.log",
                maxBytes=MAX_LOG_FILE_SIZE,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    )

    configure_logging._configured = True


def bind_log_context(
    *,
    request_id: str | None = None,
    task_id: str | None = None,
) -> tuple[Token[str], Token[str]]:
    """Bind request/task ids to the current execution context and return reset tokens."""
    resolved_request_id = request_id or new_id()
    resolved_task_id = task_id or resolved_request_id
    return REQUEST_ID_CTX.set(resolved_request_id), TASK_ID_CTX.set(resolved_task_id)


def reset_log_context(tokens: tuple[Token[str], Token[str]]) -> None:
    """Restore the previous logging context using tokens from `bind_log_context`."""
    request_token, task_token = tokens
    REQUEST_ID_CTX.reset(request_token)
    TASK_ID_CTX.reset(task_token)


def get_request_id() -> str:
    """Return the current request id from the logging context."""
    return REQUEST_ID_CTX.get()


def get_task_id() -> str:
    """Return the current task id from the logging context."""
    return TASK_ID_CTX.get()


def new_id() -> str:
    """Generate a new opaque identifier for request/task correlation."""
    return uuid4().hex


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured under the application's logging tree."""
    return logging.getLogger(name)


def _build_handler(handler: logging.Handler) -> logging.Handler:
    """Attach the shared formatter and context filter to one logging handler."""
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    return handler


def _clear_logger_handlers(logger: logging.Logger) -> None:
    """Flush and close all handlers on a logger before reconfiguration."""
    # Tests reconfigure logging multiple times, so handlers must be closed before paths disappear.
    for handler in logger.handlers:
        handler.flush()
        handler.close()


def _reset_application_loggers() -> None:
    """Reset application loggers so prior test or runtime config does not leak into the next run."""
    logger_dict = logging.root.manager.loggerDict
    for name, logger in logger_dict.items():
        if not name.startswith("app") or not isinstance(logger, logging.Logger):
            continue

        _clear_logger_handlers(logger)
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)
        logger.disabled = False
        logger.propagate = True
