"""Tests for worker.scanner — streaming scan, verdict mapping, chunk reader.

The real ``_instream`` clamd socket call is live-only (``# pragma: no cover``);
here it is monkeypatched so the public ``scan`` path and verdict mapping are
fully exercised without a clamd daemon.
"""

import pytest

from worker.config import WorkerConfig
from worker.scanner import (
    ClamAVScanner,
    Scanner,
    ScanVerdict,
    _ChunkReader,
    get_scanner,
)


def test_get_scanner_builds_clamav_scanner_from_config():
    cfg = WorkerConfig(CLAMAV_HOST="av", CLAMAV_PORT=3311, CLAMAV_TIMEOUT_SECONDS=42)
    scanner = get_scanner(cfg)
    assert isinstance(scanner, ClamAVScanner)
    assert isinstance(scanner, Scanner)
    assert scanner.host == "av"
    assert scanner.port == 3311
    assert scanner.timeout == 42


def test_verdict_clean_for_ok_status():
    assert ClamAVScanner._verdict({"stream": ("OK", None)}) is ScanVerdict.CLEAN


def test_verdict_infected_for_found_status():
    raw = {"stream": ("FOUND", "Eicar-Test-Signature")}
    assert ClamAVScanner._verdict(raw) is ScanVerdict.INFECTED


@pytest.mark.anyio
async def test_scan_clean_consumes_chunk_stream(monkeypatch):
    scanner = ClamAVScanner("av", 3310, 30)
    seen: list[bytes] = []

    def fake_instream(chunks):
        seen.append(b"".join(chunks))
        return {"stream": ("OK", None)}

    monkeypatch.setattr(scanner, "_instream", fake_instream)
    assert await scanner.scan([b"hel", b"lo"]) is ScanVerdict.CLEAN
    assert seen == [b"hello"]


@pytest.mark.anyio
async def test_scan_infected(monkeypatch):
    scanner = ClamAVScanner("av", 3310, 30)
    monkeypatch.setattr(scanner, "_instream", lambda chunks: {"stream": ("FOUND", "X")})
    assert await scanner.scan([b"evil"]) is ScanVerdict.INFECTED


# ── _ChunkReader: file-like read() over a chunk iterator (for clamd.instream) ──


def test_chunk_reader_reads_across_chunk_boundaries():
    reader = _ChunkReader([b"abc", b"def", b"gh"])
    assert reader.read(2) == b"ab"  # within first chunk
    assert reader.read(4) == b"cdef"  # spans the first/second chunk boundary
    assert reader.read(10) == b"gh"  # asks past the end → returns the remainder
    assert reader.read(10) == b""  # exhausted


def test_chunk_reader_read_all_with_negative_size():
    reader = _ChunkReader([b"ab", b"cd"])
    assert reader.read(-1) == b"abcd"  # drains the whole iterator
    assert reader.read(-1) == b""  # nothing left
