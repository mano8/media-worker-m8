"""Tests for worker.media_types — format → MIME mapping."""

import pytest

from worker.media_types import DEFAULT_CONTENT_TYPE, content_type_for_format


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("JPEG", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("JPG", "image/jpeg"),
        ("PNG", "image/png"),
        ("WEBP", "image/webp"),
        ("webp", "image/webp"),
        ("GIF", "image/gif"),
        ("AVIF", "image/avif"),
    ],
)
def test_known_formats(fmt, expected):
    assert content_type_for_format(fmt) == expected


def test_unknown_format_falls_back_to_octet_stream():
    assert content_type_for_format("TIFF") == DEFAULT_CONTENT_TYPE
    assert content_type_for_format("") == DEFAULT_CONTENT_TYPE
