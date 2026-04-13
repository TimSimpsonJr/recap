"""Shared test fixtures."""
import pathlib
import pytest


@pytest.fixture
def tmp_vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary vault structure for testing."""
    meetings = tmp_path / "Work" / "Meetings"
    meetings.mkdir(parents=True)
    people = tmp_path / "Work" / "People"
    people.mkdir(parents=True)
    companies = tmp_path / "Work" / "Companies"
    companies.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tmp_recordings(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary recordings directory."""
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    return recordings
