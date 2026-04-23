from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from app.infrastructure.logging import (
    JsonFormatter,
    bind_log_context,
    configure_logging,
    get_logger,
    reset_log_context,
)


class LoggingTests(unittest.TestCase):
    """Verify that logging helpers emit the expected structured output."""

    def test_json_formatter_includes_request_and_task_ids(self) -> None:
        """Structured log formatting should include bound request and task identifiers."""
        tokens = bind_log_context(request_id="req-1", task_id="task-1")
        try:
            record = logging.LogRecord(
                name="app.integration.foks.read",
                level=logging.INFO,
                pathname=__file__,
                lineno=10,
                msg="message",
                args=(),
                exc_info=None,
            )
            payload = json.loads(JsonFormatter().format(record))
        finally:
            reset_log_context(tokens)

        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["task_id"], "task-1")
        self.assertEqual(payload["logger"], "app.integration.foks.read")

    def test_configure_logging_writes_logs_to_files(self) -> None:
        """Log routing should split application and integration events into the right files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                configure_logging(force=True, log_dir=temp_dir)
                tokens = bind_log_context(request_id="req-file", task_id="task-file")
                try:
                    get_logger("app.api").info("app_message", extra={"event": "app_message"})
                    get_logger("app.integration.foks.read").info(
                        "integration_message",
                        extra={"event": "integration_message"},
                    )
                finally:
                    reset_log_context(tokens)

                app_log = Path(temp_dir) / "app.log"
                integration_log = Path(temp_dir) / "foks-integration.log"

                self.assertTrue(app_log.exists())
                self.assertTrue(integration_log.exists())
                self.assertIn("app_message", app_log.read_text(encoding="utf-8"))
                self.assertIn("integration_message", app_log.read_text(encoding="utf-8"))
                self.assertIn("integration_message", integration_log.read_text(encoding="utf-8"))
                self.assertNotIn("app_message", integration_log.read_text(encoding="utf-8"))
            finally:
                logging.shutdown()
                configure_logging(force=True, log_dir="logs")


if __name__ == "__main__":
    unittest.main()
