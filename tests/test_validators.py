"""Tests for app.utils.validators."""
from __future__ import annotations

import io

import pytest

from app.utils.validators import is_valid_pdf_filename, is_valid_pdf_bytes, safe_project_name


class TestIsValidPdfFilename:
    def test_accepts_pdf_extension(self):
        assert is_valid_pdf_filename("report.pdf") is True

    def test_accepts_pdf_with_path(self):
        assert is_valid_pdf_filename("some/path/file.PDF") is True

    def test_rejects_non_pdf(self):
        assert is_valid_pdf_filename("report.docx") is False

    def test_rejects_empty(self):
        assert is_valid_pdf_filename("") is False

    def test_rejects_none(self):
        assert is_valid_pdf_filename(None) is False  # type: ignore[arg-type]

    def test_rejects_pdf_without_extension(self):
        assert is_valid_pdf_filename("report") is False


class TestIsValidPdfBytes:
    def test_accepts_pdf_magic_bytes(self, sample_pdf_bytes: bytes):
        assert is_valid_pdf_bytes(sample_pdf_bytes) is True

    def test_accepts_pdf_from_file_storage(self, sample_pdf_bytes: bytes):
        class FakeStorage:
            def __init__(self, data: bytes, name: str = "f.pdf"):
                self.stream = io.BytesIO(data)
                self.filename = name

        fs = FakeStorage(sample_pdf_bytes)
        assert is_valid_pdf_bytes(fs) is True

    def test_rejects_non_pdf_bytes(self):
        assert is_valid_pdf_bytes(b"not a pdf") is False
        assert is_valid_pdf_bytes(b"\x89PNG\r\n\x1a\n") is False
        assert is_valid_pdf_bytes(b"") is False

    def test_rejects_none(self):
        assert is_valid_pdf_bytes(None) is False  # type: ignore[arg-type]


class TestSafeProjectName:
    def test_strips_path_separators(self):
        assert safe_project_name("../etc/passwd") == "etcpasswd"
        assert safe_project_name("foo/bar") == "foobar"
        assert safe_project_name("a\\b") == "ab"

    def test_removes_dangerous_chars(self):
        assert safe_project_name("hello;world") == "helloworld"
        assert safe_project_name("foo bar") == "foobar"

    def test_strips_leading_dots(self):
        assert safe_project_name("..hidden") == "hidden"
        assert safe_project_name(".config") == "config"

    def test_collapses_underscores(self):
        assert safe_project_name("foo___bar") == "foo_bar"

    def test_lowercases(self):
        assert safe_project_name("MyProject") == "myproject"

    def test_empty_after_cleaning_returns_default(self):
        assert safe_project_name("...") == "project"
        assert safe_project_name("///") == "project"

    def test_truncates_to_max_length(self):
        long_name = "a" * 100
        assert len(safe_project_name(long_name, max_length=20)) == 20

    def test_preserves_hyphens_digits(self):
        assert safe_project_name("my-project_2024") == "my-project_2024"