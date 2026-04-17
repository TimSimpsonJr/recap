"""Fixtures for the integration tier — real ML libraries, heavy setup.

All fixtures here are session-scoped so model loading happens once per
`pytest -m integration` invocation. Regular `pytest -q` never touches
this file because the tier is excluded by default.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def cuda_guard():
    """Skip if CUDA is not available. Lazy torch import.

    Session-scoped so model fixtures can depend on it without ScopeMismatch.
    """
    pytest.importorskip("torch")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")


@pytest.fixture(scope="session")
def parakeet_asr_model(cuda_guard):
    """Load Parakeet ASR model once per session."""
    import nemo.collections.asr as nemo_asr
    import torch

    model = nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2")
    model = model.to("cuda")
    yield model
    del model
    torch.cuda.empty_cache()


@pytest.fixture(scope="session")
def sortformer_diarizer_model(cuda_guard):
    """Load NeMo Sortformer diarization model once per session.

    Mirrors the production loader at recap/pipeline/diarize.py:16 — same
    class (SortformerEncLabelModel), same from_pretrained, same .diarize()
    surface.
    """
    from nemo.collections.asr.models import SortformerEncLabelModel
    import torch

    model = SortformerEncLabelModel.from_pretrained(
        "nvidia/diar_streaming_sortformer_4spk-v2.1"
    )
    model = model.to("cuda")
    yield model
    del model
    torch.cuda.empty_cache()
