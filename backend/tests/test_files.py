from pathlib import Path

from app.services.files import safe_filename


def test_filename_is_sanitized():
    assert safe_filename("../../private key.txt") == "private_key.txt"


def test_pdf_filename_is_allowed_and_sanitized():
    assert safe_filename("../../report 2026.pdf") == "report_2026.pdf"
