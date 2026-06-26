"""Pluggable antivirus scanner boundary.

``scan_object`` depends only on the :class:`Scanner` protocol, so the ClamAV
implementation can be swapped (e.g. for a fake in tests) without touching task
code. The default :class:`ClamAVScanner` streams bytes to the clamd daemon over
TCP — there is **no** ClamAV binary or virus database bundled in the worker
image; the ``clamav`` compose service owns those.

The scan input is a **chunk iterator** (``Iterable[bytes]``), not a single
``bytes`` blob: the source is pulled from object storage chunk-by-chunk and fed
straight to the clamd ``INSTREAM`` socket, so the worker never materialises a
whole (size-capped) object in memory (security plan P1.2).
"""

import asyncio
import enum
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from worker.config import WorkerConfig


class ScanVerdict(str, enum.Enum):
    """Outcome of scanning an object's bytes."""

    CLEAN = "clean"
    INFECTED = "infected"


@runtime_checkable
class Scanner(Protocol):
    """Async antivirus scanner: classify a stream of byte chunks."""

    async def scan(self, chunks: Iterable[bytes]) -> ScanVerdict:
        """Return the verdict for the object yielded by *chunks*."""
        ...


class _ChunkReader:
    """Minimal read-only file object over a byte-chunk iterator.

    clamd's ``instream`` pulls its buffer with ``buff.read(max_chunk_size)``;
    this adapter satisfies that contract while only ever holding the unconsumed
    tail of one source chunk plus the bytes clamd has asked for — so the full
    object is never buffered. Consumed synchronously inside the clamd worker
    thread, where the underlying storage iterator's blocking reads also run.
    """

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._it = iter(chunks)
        self._buf = bytearray()
        self._exhausted = False

    def read(self, size: int = -1) -> bytes:
        """Return up to *size* bytes (all remaining when *size* < 0)."""
        while not self._exhausted and (size < 0 or len(self._buf) < size):
            try:
                self._buf.extend(next(self._it))
            except StopIteration:
                self._exhausted = True
        if size < 0:
            chunk = bytes(self._buf)
            self._buf.clear()
            return chunk
        chunk = bytes(self._buf[:size])
        del self._buf[:size]
        return chunk


class ClamAVScanner:
    """Default scanner backed by a clamd daemon reached over TCP."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def scan(self, chunks: Iterable[bytes]) -> ScanVerdict:
        """Stream *chunks* to clamd in a worker thread and map the verdict."""
        raw = await asyncio.to_thread(self._instream, chunks)
        return self._verdict(raw)

    def _instream(
        self, chunks: Iterable[bytes]
    ) -> Any:  # pragma: no cover - live clamd socket
        """Stream chunks to the clamd daemon and return its raw response."""
        import clamd

        client = clamd.ClamdNetworkSocket(
            host=self.host, port=self.port, timeout=self.timeout
        )
        return client.instream(_ChunkReader(chunks))

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
