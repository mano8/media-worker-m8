"""Pluggable antivirus scanner boundary.

``scan_object`` depends only on the :class:`Scanner` protocol, so the ClamAV
implementation can be swapped (e.g. for a fake in tests) without touching task
code. The default :class:`ClamAVScanner` streams bytes to the clamd daemon over
TCP — there is **no** ClamAV binary or virus database bundled in the worker
image; the ``clamav`` compose service owns those.
"""

import asyncio
import enum
import io
from typing import Any, Protocol, runtime_checkable

from worker.config import WorkerConfig


class ScanVerdict(str, enum.Enum):
    """Outcome of scanning an object's bytes."""

    CLEAN = "clean"
    INFECTED = "infected"


@runtime_checkable
class Scanner(Protocol):
    """Async antivirus scanner: classify a blob of bytes."""

    async def scan(self, data: bytes) -> ScanVerdict:
        """Return the verdict for *data*."""
        ...


class ClamAVScanner:
    """Default scanner backed by a clamd daemon reached over TCP."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def scan(self, data: bytes) -> ScanVerdict:
        """Stream *data* to clamd in a worker thread and map the verdict."""
        raw = await asyncio.to_thread(self._instream, data)
        return self._verdict(raw)

    def _instream(self, data: bytes) -> Any:  # pragma: no cover - live clamd socket
        """Send bytes to the clamd daemon and return its raw response."""
        import clamd

        client = clamd.ClamdNetworkSocket(
            host=self.host, port=self.port, timeout=self.timeout
        )
        return client.instream(io.BytesIO(data))

    @staticmethod
    def _verdict(raw: Any) -> ScanVerdict:
        """Map a clamd ``INSTREAM`` response to a :class:`ScanVerdict`.

        clamd returns ``{"stream": ("OK", None)}`` for a clean blob and
        ``{"stream": ("FOUND", "<signature>")}`` when a signature matches.
        """
        status = raw["stream"][0]
        return ScanVerdict.CLEAN if status == "OK" else ScanVerdict.INFECTED


def get_scanner(config: WorkerConfig) -> Scanner:
    """Build the configured scanner implementation (ClamAV by default)."""
    return ClamAVScanner(
        host=config.CLAMAV_HOST,
        port=config.CLAMAV_PORT,
        timeout=config.CLAMAV_TIMEOUT_SECONDS,
    )
