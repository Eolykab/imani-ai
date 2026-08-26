import pytest

from app.services.voice import VoiceUnavailable, extract_transcript


def test_extracts_labelled_hailo_transcript():
    output = "INFO Loading model\nTranscription: Add buy HDMI cable to my tasks\n"
    assert extract_transcript(output) == "Add buy HDMI cable to my tasks"


def test_does_not_treat_multiple_diagnostic_lines_as_speech():
    with pytest.raises(VoiceUnavailable):
        extract_transcript("setup complete\ndevice ready\n")


def test_extracts_current_hailo_cli_separator_output():
    output = "Architecture: hailo8\nTranscribing (1 chunk(s))...\n--------------------------------------------------\nAdd buy milk to my tasks\n--------------------------------------------------\n(1.2s)\n"
    assert extract_transcript(output) == "Add buy milk to my tasks"
