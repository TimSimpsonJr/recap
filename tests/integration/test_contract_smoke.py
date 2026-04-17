"""CPU-safe contract smoke tests.

These assert the shape and importability of real libraries we depend on.
Marked `@pytest.mark.integration`; opt-in via `pytest -m integration`.
"""
import pytest

pytestmark = pytest.mark.integration

# Tests added in Task 2.
