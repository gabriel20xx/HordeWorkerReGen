"""Tests for configure_logger_format file-logging behaviour."""

import importlib
import os
import sys
from pathlib import Path

import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def _restore_logger():
    """Remove all loguru handlers added during the test and restore the default handler."""
    logger.remove()
    yield
    logger.remove()
    # Restore a basic stderr sink so other tests are not affected
    logger.add(sys.stderr)


def _reload_logger_config():
    """Return a freshly imported configure_logger_format callable."""
    import horde_worker_regen.logger_config as mod

    importlib.reload(mod)
    return mod.configure_logger_format, mod._LOGS_DIR


class TestConfigureLoggerFormatFileLogging:
    """Verify that configure_logger_format creates log files as documented."""

    def test_main_process_creates_bridge_and_trace_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """process_id=None should create bridge.log and trace.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)

        assert (tmp_path / "bridge.log").exists(), "bridge.log should be created for the main process"
        assert (tmp_path / "trace.log").exists(), "trace.log should be created for the main process"

    def test_subprocess_creates_numbered_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """process_id=1 should create bridge_1.log and trace_1.log."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=1)

        assert (tmp_path / "bridge_1.log").exists(), "bridge_1.log should be created for process 1"
        assert (tmp_path / "trace_1.log").exists(), "trace_1.log should be created for process 1"

    def test_bridge_log_receives_info_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """bridge.log should capture INFO-level messages."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("test info message for bridge")
        logger.complete()  # flush all pending log messages

        content = (tmp_path / "bridge.log").read_text(encoding="utf-8")
        assert "test info message for bridge" in content

    def test_trace_log_receives_warning_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """trace.log should capture WARNING-level messages."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.warning("test warning for trace")
        logger.complete()

        content = (tmp_path / "trace.log").read_text(encoding="utf-8")
        assert "test warning for trace" in content

    def test_trace_log_does_not_receive_info_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """trace.log should NOT capture INFO-level messages (WARNING+ only)."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("info only message")
        logger.complete()

        content = (tmp_path / "trace.log").read_text(encoding="utf-8")
        assert "info only message" not in content

    def test_log_files_have_no_ansi_escape_codes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log files should contain plain text without ANSI escape sequences."""
        import horde_worker_regen.logger_config as mod

        monkeypatch.setattr(mod, "_LOGS_DIR", tmp_path)
        monkeypatch.delenv("AIWORKER_LOG_LEVEL", raising=False)
        monkeypatch.delenv("AIWORKER_DEBUG", raising=False)

        mod.configure_logger_format(process_id=None)
        logger.info("plain text check")
        logger.complete()

        content = (tmp_path / "bridge.log").read_text(encoding="utf-8")
        assert "\x1b[" not in content, "Log file should not contain ANSI escape codes"

    def test_logs_directory_is_created_automatically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
