"""Tests for configure_logger_format file-logging behaviour."""

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from loguru import logger


def _find_log(logs_dir: Path, log_type: str, filename: str) -> Path | None:
    """Resolve a log file under the date/type subdirectory layout.

    Files are written to ``<logs_dir>/<YYYY-MM-DD>/<log_type>/<filename>`` (the date directory
    is created by loguru from the ``{time:YYYY-MM-DD}`` token in the sink path). A glob is used
    so the test does not depend on today's exact date string and is robust across a midnight
    rollover. Returns the path if it exists, otherwise ``None``.

    Note: sinks use ``delay=True``, so a file only appears once a record matching that sink's
    level/filter has actually been emitted — tests must log a triggering message first.
    """
    matches = list(logs_dir.glob(f"*/{log_type}/{filename}"))
    return matches[0] if matches else None


def _webui_info(message: str) -> None:
    """Emit an INFO record whose logger name is within ``horde_worker_regen.webui``.

    The webui sink filters on ``record["name"]``; patching the name lets a test exercise that
    sink without importing a real webui module.
    """
    logger.patch(lambda r: r.update(name="horde_worker_regen.webui.server")).info(message)


@pytest.fixture(autouse=True)
def _restore_logger() -> Generator[None, None, None]:
    """Remove all loguru handlers added during the test and restore the default handler."""
    logger.remove()
    yield
    logger.remove()
    # Restore a basic stderr sink so other tests are not affected
    logger.add(sys.stderr)


class TestConfigureLoggerFormatFileLogging:
    """Verify that configure_logger_format creates log files as documented."""

    def test_main_process_creates_bridge_and_trace_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """process_id=None should create bridge.log and trace.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        # trace/ uses delay=True and only opens its file on the first ERROR+ record.
        logger.error("trigger trace creation")
        logger.complete()

        assert _find_log(tmp_path, "bridge", "bridge.log") is not None, "bridge.log should be created for the main process"
        assert _find_log(tmp_path, "trace", "trace.log") is not None, "trace.log should be created for the main process"

    def test_subprocess_creates_numbered_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """process_id=1 should create bridge_1.log and trace_1.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=1)
        logger.error("trigger trace creation")
        logger.complete()

        assert _find_log(tmp_path, "bridge", "bridge_1.log") is not None, "bridge_1.log should be created for process 1"
        assert _find_log(tmp_path, "trace", "trace_1.log") is not None, "trace_1.log should be created for process 1"

    def test_bridge_log_receives_info_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """bridge.log should capture INFO-level messages."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("test info message for bridge")
        logger.complete()  # flush all pending log messages

        bridge_log = _find_log(tmp_path, "bridge", "bridge.log")
        assert bridge_log is not None, "bridge.log should be created"
        assert "test info message for bridge" in bridge_log.read_text(encoding="utf-8")

    def test_trace_log_receives_error_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """trace.log should capture ERROR-level messages (errors only, per logs/README.md)."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.error("test error for trace")
        logger.complete()

        trace_log = _find_log(tmp_path, "trace", "trace.log")
        assert trace_log is not None, "trace.log should be created"
        assert "test error for trace" in trace_log.read_text(encoding="utf-8")

    def test_trace_log_does_not_receive_info_or_warning_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """trace.log should NOT capture INFO or WARNING messages (ERROR+ only)."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("info only message")
        logger.warning("warning only message")
        logger.complete()

        # With only INFO/WARNING emitted, the ERROR-level trace sink never opens its file
        # (delay=True); treat a missing file as "no leaked messages".
        trace_log = _find_log(tmp_path, "trace", "trace.log")
        content = trace_log.read_text(encoding="utf-8") if trace_log else ""
        assert "info only message" not in content
        assert "warning only message" not in content

    def test_log_files_have_no_ansi_escape_codes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log files should contain plain text without ANSI escape sequences."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("plain text check")
        logger.complete()

        bridge_log = _find_log(tmp_path, "bridge", "bridge.log")
        assert bridge_log is not None, "bridge.log should be created"
        assert "\x1b[" not in bridge_log.read_text(encoding="utf-8"), "Log file should not contain ANSI escape codes"

    def test_logs_directory_is_created_automatically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """configure_logger_format should create the logs directory if it does not exist."""
        import horde_worker_regen.logger_config as mod

        nested_logs = tmp_path / "nested" / "logs"
        assert not nested_logs.exists()

        monkeypatch.setattr(mod, "_LOGS_DIR", nested_logs)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)

        assert nested_logs.is_dir(), "logs directory should be created automatically"

    def test_enable_stderr_false_still_writes_to_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """enable_stderr=False (--no-logging) should still write to log files."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None, enable_stderr=False)
        logger.info("no-logging file message")
        logger.complete()

        bridge_log = _find_log(tmp_path, "bridge", "bridge.log")
        assert bridge_log is not None, "bridge.log should be created even with stderr disabled"
        assert "no-logging file message" in bridge_log.read_text(encoding="utf-8")

    def test_main_process_creates_crash_and_webui_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """process_id=None should also create crash.log and webui.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        # crash/ (CRITICAL only) and webui/ (webui module only) use delay=True; emit a matching
        # record for each so the sink opens its file.
        logger.critical("trigger crash log")
        _webui_info("trigger webui log")
        logger.complete()

        assert _find_log(tmp_path, "crash", "crash.log") is not None, "crash.log should be created for the main process"
        assert _find_log(tmp_path, "webui", "webui.log") is not None, "webui.log should be created for the main process"

    def test_subprocess_does_not_create_crash_or_webui_logs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Subprocesses should NOT create crash.log or webui.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=2)
        # Even when matching records are emitted, subprocesses must not create these sinks.
        logger.critical("would-be crash")
        _webui_info("would-be webui")
        logger.complete()

        assert _find_log(tmp_path, "crash", "crash.log") is None, "crash.log should NOT be created for subprocesses"
        assert _find_log(tmp_path, "webui", "webui.log") is None, "webui.log should NOT be created for subprocesses"

    def test_crash_log_receives_critical_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """crash.log should capture CRITICAL-level messages."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.critical("test critical for crash log")
        logger.complete()

        crash_log = _find_log(tmp_path, "crash", "crash.log")
        assert crash_log is not None, "crash.log should be created"
        assert "test critical for crash log" in crash_log.read_text(encoding="utf-8")

    def test_crash_log_does_not_receive_error_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """crash.log should NOT capture ERROR or lower messages."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.error("error only message")
        logger.complete()

        # ERROR never opens the CRITICAL-only crash sink (delay=True); a missing file means
        # nothing leaked.
        crash_log = _find_log(tmp_path, "crash", "crash.log")
        content = crash_log.read_text(encoding="utf-8") if crash_log else ""
        assert "error only message" not in content

    def test_file_format_includes_source_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """bridge.log entries should include module:function:line source location."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("source location test")
        logger.complete()

        bridge_log = _find_log(tmp_path, "bridge", "bridge.log")
        assert bridge_log is not None, "bridge.log should be created"
        content = bridge_log.read_text(encoding="utf-8")
        # Format: timestamp | level | module:function:line | message
        # The line should contain at least one colon-separated location field
        assert "source location test" in content
        # Find the line containing our message and verify it has the location field
        matching_lines = [line for line in content.splitlines() if "source location test" in line]
        assert matching_lines, "Message should appear in log file"
        log_line = matching_lines[0]
        parts = log_line.split(" | ")
        assert len(parts) >= 4, f"Log line should have 4 '|'-separated fields, got: {log_line!r}"
        location_field = parts[2]
        assert ":" in location_field, f"Location field should be 'module:function:line', got: {location_field!r}"
