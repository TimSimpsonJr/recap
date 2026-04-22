"""Tests for daemon logging setup."""
import logging
from recap.daemon.logging_setup import setup_logging


class TestSetupLogging:
    def setup_method(self):
        # Clean up recap logger handlers between tests
        logger = logging.getLogger("recap")
        logger.handlers.clear()

    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        assert log_dir.exists()

    def test_configures_root_logger(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap")
        assert logger.level == logging.INFO
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "TimedRotatingFileHandler" in handler_types
        assert "StreamHandler" in handler_types

    def test_log_file_created_on_first_message(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap.test_logging")
        logger.info("test message")
        log_files = list(log_dir.glob("recap.log*"))
        assert len(log_files) >= 1

    def test_idempotent(self, tmp_path):
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap")
        # Should not have duplicate handlers
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert handler_types.count("TimedRotatingFileHandler") == 1
        assert handler_types.count("StreamHandler") == 1

    def test_respects_recap_log_level_env_var(self, tmp_path, monkeypatch):
        """RECAP_LOG_LEVEL=DEBUG elevates the recap logger to DEBUG so the
        diagnostic instrumentation added for issue #30 can be activated at
        runtime without touching code."""
        monkeypatch.setenv("RECAP_LOG_LEVEL", "DEBUG")
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap")
        assert logger.level == logging.DEBUG

    def test_unknown_log_level_falls_back_to_info(self, tmp_path, monkeypatch):
        """Typos in the env var must not silently disable logging."""
        monkeypatch.setenv("RECAP_LOG_LEVEL", "NOTALEVEL")
        log_dir = tmp_path / "logs"
        setup_logging(log_dir, retention_days=7)
        logger = logging.getLogger("recap")
        assert logger.level == logging.INFO
