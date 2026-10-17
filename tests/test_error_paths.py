"""
tests/test_error_paths.py
─────────────────────────────────────────────────────────────
Error handlers must work when they run.

Both defects covered here were invisible to the happy path and were found by resolving every
global a function reads (`test_framework_consistency.test_no_function_reads_an_undefined_global`):

  * `server/state_manager.py` logged a variable from a *different* method inside its
    metadata-extraction handler, so the handler raised NameError and the error escaped
    instead of being logged.
  * `server/telegram_listener.py` used `json` and `time` without importing them, and both
    call sites sit inside `try/except` blocks that swallowed the NameError — so the daily
    report's "already sent today" state was never read back or written, and the scheduled
    report re-fired after every restart during the 21:00 minute.

A handler that raises is worse than no handler, so each of these is exercised here rather
than assumed.
"""

import json
import os
import unittest
from unittest.mock import mock_open, patch

import server.telegram_listener as telegram_listener_module
from server.state_manager import strategy_registry
from server.telegram_listener import TelegramListener


class TestMetadataExtractionErrorPath(unittest.TestCase):
    def test_unreadable_strategy_file_is_logged_not_raised(self):
        """
        A strategy file that cannot be read must degrade to metadata defaults, not crash.

        With the `py_path` bug the warning raised NameError, so the exception escaped
        `_infer_metadata` and took down whatever was registering strategies.
        """
        target = os.path.join("strategies", "UnreadableStrategy.py")

        with patch("server.state_manager.os.path.exists", return_value=True), \
             patch("builtins.open", side_effect=OSError("permission denied")), \
             self.assertLogs("StateManager", level="WARNING") as captured:
            meta = strategy_registry._infer_metadata("UnreadableStrategy.py", filepath_override=target)

        self.assertIsInstance(meta, dict)
        self.assertTrue(
            any("Metadata extraction failed" in line for line in captured.output),
            captured.output,
        )
        self.assertEqual(meta.get("display_name"), "Unreadable Strategy")


class TestTelegramListenerDailyReportState(unittest.TestCase):
    def test_scheduler_dependencies_are_imported(self):
        """The daily-report scheduler uses json and time; both must be module imports."""
        missing = [
            name for name in ("json", "time")
            if not hasattr(telegram_listener_module, name)
        ]
        self.assertEqual(missing, [], "the daily-report scheduler would raise NameError")

    def test_persisted_report_date_is_restored(self):
        """
        The listener must read back the date it last reported, or it re-fires after a restart.

        The read used to raise NameError inside a bare `except Exception: pass`, so
        `last_reported_date` stayed empty and the 21:00 report was re-sent on every process
        start during that minute.
        """
        state = {"date": "2026-10-14", "timestamp": 1}

        with patch("server.telegram_listener.os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=json.dumps(state))):
            listener = TelegramListener()

        self.assertEqual(listener.last_reported_date, "2026-10-14")


if __name__ == "__main__":
    unittest.main()
