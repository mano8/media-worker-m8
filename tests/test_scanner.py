"""Tests for worker.scanner — verdict mapping + factory.

The real ``_instream`` clamd socket call is live-only (``# pragma: no cover``);
here it is monkeypatched so the public ``scan`` path and verdict mapping are
fully exercised without a clamd daemon.
"""

import pytest

from worker.config import WorkerConfig
from worker.scanner import ClamAVScanner, ScanVerdict, Scanner, get_scanner


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
async def test_scan_clean(monkeypatch):
    scanner = ClamAVScanner("av", 3310, 30)
    monkeypatch.setattr(scanner, "_instream", lambda data: {"stream": ("OK", None)})
    assert await scanner.scan(b"hello") is ScanVerdict.CLEAN


@pytest.mark.anyio
async def test_scan_infected(monkeypatch):
    scanner = ClamAVScanner("av", 3310, 30)
    monkeypatch.setattr(scanner, "_instream", lambda data: {"stream": ("FOUND", "X")})
    assert await scanner.scan(b"evil") is ScanVerdict.INFECTED
