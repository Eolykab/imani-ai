from pathlib import Path

from app.services.files import safe_filename


def test_filename_is_sanitized():
    assert safe_filename("../../private key.txt") == "private_key.txt"

