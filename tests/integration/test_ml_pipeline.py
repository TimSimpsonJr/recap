"""GPU-required ML pipeline tests.

Load real models and exercise the batch pipeline end-to-end. Skipped
when CUDA is unavailable via the cuda_guard fixture.
"""
import pytest

pytestmark = pytest.mark.integration

# Tests added in Task 9.
