"""Tests for NeMo speaker diarization."""
from unittest.mock import patch, MagicMock
from recap.pipeline.diarize import diarize, assign_speakers
from recap.models import TranscriptResult, Utterance


class TestDiarize:
    def test_parses_nemo_string_lines_into_segment_dicts(self, tmp_path):
        """NeMo's Sortformer returns ``List[List[str]]`` where the inner list
        holds ``"start end speaker_N"`` lines (see
        ``nemo/collections/asr/parts/utils/speaker_utils.py::
        generate_diarization_output_lines``). ``diarize()`` must unwrap the
        outer per-file list and parse each line into the
        ``{"start", "end", "speaker"}`` dict shape ``assign_speakers``
        consumes."""
        mock_model = MagicMock()
        mock_model.diarize.return_value = [[
            "0.500 3.120 speaker_0",
            "3.510 7.260 speaker_1",
        ]]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model"):
                segments = diarize(audio_path=tmp_path / "test.flac", device="cpu")

        assert len(segments) == 2
        assert segments[0] == {"start": 0.5, "end": 3.12, "speaker": "SPEAKER_00"}
        assert segments[1] == {"start": 3.51, "end": 7.26, "speaker": "SPEAKER_01"}

    def test_handles_empty_diarize_output(self, tmp_path):
        """A silent clip returns ``[[]]`` (outer per-file list wrapping an
        empty segment list). ``diarize()`` must degrade to ``[]`` without
        raising."""
        mock_model = MagicMock()
        mock_model.diarize.return_value = [[]]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model"):
                segments = diarize(audio_path=tmp_path / "test.flac", device="cpu")

        assert segments == []

    def test_normalizes_speaker_label_to_uppercase_zero_padded(self, tmp_path):
        """NeMo emits ``speaker_0`` / ``speaker_12``; downstream code
        (``tests/test_analyze.py``, clip endpoint, frontmatter) uses
        ``SPEAKER_00`` / ``SPEAKER_12``. ``diarize()`` owns this
        normalisation so consumers never see a mix of conventions."""
        mock_model = MagicMock()
        mock_model.diarize.return_value = [[
            "0.000 1.000 speaker_3",
            "1.000 2.000 speaker_12",
        ]]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model"):
                segments = diarize(audio_path=tmp_path / "test.flac", device="cpu")

        assert segments[0]["speaker"] == "SPEAKER_03"
        assert segments[1]["speaker"] == "SPEAKER_12"

    def test_unloads_model(self, tmp_path):
        mock_model = MagicMock()
        mock_model.diarize.return_value = [[]]

        with patch("recap.pipeline.diarize._load_diarization_model", return_value=mock_model):
            with patch("recap.pipeline.diarize._unload_model") as unload:
                diarize(audio_path=tmp_path / "test.flac", device="cpu")
                unload.assert_called_once()


class TestAssignSpeakers:
    def test_assigns_speakers_by_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
                Utterance(speaker="UNKNOWN", start=5.0, end=8.0, text="Hi there"),
            ],
            raw_text="Hello Hi there",
            language="en",
        )
        speaker_segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
        ]

        result = assign_speakers(transcript, speaker_segments)
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[1].speaker == "SPEAKER_01"

    def test_does_not_mutate_input(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        segments = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = assign_speakers(transcript, segments)
        assert transcript.utterances[0].speaker == "UNKNOWN"
        assert result.utterances[0].speaker == "SPEAKER_00"

    def test_handles_no_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=20.0, end=25.0, text="Late"),
            ],
            raw_text="Late",
            language="en",
        )
        segments = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}]
        result = assign_speakers(transcript, segments)
        assert result.utterances[0].speaker == "UNKNOWN"

    def test_picks_best_overlap(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=4.0, end=7.0, text="overlap"),
            ],
            raw_text="overlap",
            language="en",
        )
        segments = [
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},  # 1s overlap
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},  # 2s overlap
        ]
        result = assign_speakers(transcript, segments)
        assert result.utterances[0].speaker == "SPEAKER_01"

    def test_empty_segments_keeps_unknown(self):
        transcript = TranscriptResult(
            utterances=[
                Utterance(speaker="UNKNOWN", start=0.0, end=3.0, text="Hello"),
            ],
            raw_text="Hello",
            language="en",
        )
        result = assign_speakers(transcript, [])
        assert result.utterances[0].speaker == "UNKNOWN"
