import pytest

from app.services.voice import VoiceUnavailable, extract_transcript


def test_extracts_labelled_hailo_transcript():
    output = "INFO Loading model\nTranscription: Add buy HDMI cable to my tasks\n"
    assert extract_transcript(output) == "Add buy HDMI cable to my tasks"


def test_does_not_treat_multiple_diagnostic_lines_as_speech():
    with pytest.raises(VoiceUnavailable):
        extract_transcript("setup complete\ndevice ready\n")
