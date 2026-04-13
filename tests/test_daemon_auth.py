"""Tests for daemon auth token management."""
from recap.daemon.auth import ensure_auth_token, validate_token


class TestAuthToken:
    def test_creates_token_file_if_missing(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token = ensure_auth_token(token_path)
        assert token_path.exists()
        assert len(token) >= 32

    def test_reads_existing_token(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token_path.write_text("my-existing-token")
        token = ensure_auth_token(token_path)
        assert token == "my-existing-token"

    def test_validate_token_accepts_correct(self, tmp_path):
        token_path = tmp_path / "auth-token"
        token = ensure_auth_token(token_path)
        assert validate_token(token, token_path) is True

    def test_validate_token_rejects_wrong(self, tmp_path):
        token_path = tmp_path / "auth-token"
        ensure_auth_token(token_path)
        assert validate_token("wrong-token", token_path) is False
