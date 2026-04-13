"""Tests for Parakeet transcription."""
import json
from unittest.mock import patch, MagicMock
from recap.pipeline.transcribe import transcribe
from recap.models import TranscriptResult


class TestTranscribe:
    def _mock_model(self):
        mock = MagicMock()
        # NeMo transcribe returns a list of hypothesis objects
        mock_hyp = MagicMock()
        mock_hyp.text = "Hello world how are you"
        mock_hyp.timestep = {
            "segment": [
                {"start": 0.0, "end": 1.5, "text": "Hello world"},
                {"start": 1.8, "end": 3.2, "text": "how are you"},
            ]
        }
        mock.transcribe.return_value = [mock_hyp]
        return mock

    def test_returns_transcript_result(self, tmp_path):
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(
                    audio_path=tmp_path / "test.flac",
                    model_name="nvidia/parakeet-tdt-0.6b-v2",
                    device="cpu",
                )
        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 2
        assert result.utterances[0].text == "Hello world"
        assert result.utterances[0].speaker == "UNKNOWN"
        assert result.utterances[0].start == 0.0
        assert result.utterances[0].end == 1.5

    def test_raw_text_is_combined(self, tmp_path):
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(audio_path=tmp_path / "test.flac", device="cpu")
        assert "Hello world" in result.raw_text
        assert "how are you" in result.raw_text

    def test_saves_transcript_json(self, tmp_path):
        save_path = tmp_path / "transcript.json"
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                transcribe(
                    audio_path=tmp_path / "test.flac",
                    device="cpu",
                    save_transcript=save_path,
                )
        assert save_path.exists()
        data = json.loads(save_path.read_text())
        assert "utterances" in data
        assert len(data["utterances"]) == 2

    def test_unloads_model_after_transcription(self, tmp_path):
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model") as unload_mock:
                transcribe(audio_path=tmp_path / "test.flac", device="cpu")
                unload_mock.assert_called_once()

    def test_language_defaults_to_en(self, tmp_path):
        with patch("recap.pipeline.transcribe._load_model", return_value=self._mock_model()):
            with patch("recap.pipeline.transcribe._unload_model"):
                result = transcribe(audio_path=tmp_path / "test.flac", device="cpu")
        assert result.language == "en"
