"""Tests for credential storage."""
import pytest
from unittest.mock import patch, MagicMock
from recap.daemon.credentials import store_credential, get_credential, delete_credential, has_credential


class TestCredentials:
    @patch("recap.daemon.credentials.keyring")
    def test_store_credential(self, mock_kr):
        store_credential("zoho", "access_token", "my-token")
        mock_kr.set_password.assert_called_once_with("recap-zoho", "access_token", "my-token")

    @patch("recap.daemon.credentials.keyring")
    def test_get_credential(self, mock_kr):
        mock_kr.get_password.return_value = "my-token"
        result = get_credential("zoho", "access_token")
        assert result == "my-token"
        mock_kr.get_password.assert_called_once_with("recap-zoho", "access_token")

    @patch("recap.daemon.credentials.keyring")
    def test_get_missing_returns_none(self, mock_kr):
        mock_kr.get_password.return_value = None
        assert get_credential("zoho", "missing") is None

    @patch("recap.daemon.credentials.keyring")
    def test_delete_credential(self, mock_kr):
        delete_credential("zoho", "access_token")
        mock_kr.delete_password.assert_called_once_with("recap-zoho", "access_token")

    @patch("recap.daemon.credentials.keyring")
    def test_has_credential_true(self, mock_kr):
        mock_kr.get_password.return_value = "token"
        assert has_credential("zoho", "access_token") is True

    @patch("recap.daemon.credentials.keyring")
    def test_has_credential_false(self, mock_kr):
        mock_kr.get_password.return_value = None
        assert has_credential("zoho", "access_token") is False

    @patch("recap.daemon.credentials.keyring")
    def test_get_credential_error_returns_none(self, mock_kr):
        mock_kr.get_password.side_effect = Exception("keyring broken")
        assert get_credential("zoho", "token") is None
