"""Tests for worker.image_guard — pre-decode decompression-bomb defense."""

import pytest

from worker.config import WorkerConfig
from worker.image_guard import (
    DecodedImageTooLargeError,
    assert_decoded_pixels_within_limit,
    decoded_pixel_count,
)

from tests.conftest import make_png_bytes


def test_decoded_pixel_count_reads_header_dimensions():
    source = make_png_bytes(width=7, height=5)
    assert decoded_pixel_count(source) == 35


def test_within_limit_passes():
    source = make_png_bytes(width=10, height=10)
    cfg = WorkerConfig(WORKER_MAX_DECODED_PIXELS=100)
    # Exactly at the ceiling is accepted (only strictly larger is refused).
    assert assert_decoded_pixels_within_limit(source, cfg) is None


def test_over_limit_raises_before_decode():
    source = make_png_bytes(width=10, height=10)  # 100 px
    cfg = WorkerConfig(WORKER_MAX_DECODED_PIXELS=99)
    with pytest.raises(DecodedImageTooLargeError, match="exceeding the worker ceiling"):
        assert_decoded_pixels_within_limit(source, cfg)


def test_non_image_bytes_raise():
    with pytest.raises(Exception):
        decoded_pixel_count(b"not-an-image")
