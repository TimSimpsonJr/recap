"""Tests for daemon logging setup."""
import logging
import pathlib
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
