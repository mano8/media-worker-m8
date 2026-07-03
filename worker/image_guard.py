"""Pre-decode image safety guard (security plan P1.2).

A variant source is downloaded as (size-capped) encoded bytes, but its *decoded*
raster can be orders of magnitude larger — a decompression bomb. imgtools'
render pipeline calls ``Image.load()``, which allocates the full raster; this
module reads only the image **header** (``Image.open(...).size`` never decodes
pixel data) so an oversized image is refused before that allocation happens.

Pillow is used here for the header read **only**. All real image computation
(resize/encode) stays delegated to ``imgtools_m8`` — the worker's sole image
pipeline. This guard is a security preflight, not part of that pipeline.
"""

import io

from PIL import Image

from worker.config import WorkerConfig


class DecodedImageTooLargeError(Exception):
    """A variant source decodes to more pixels than the worker allows.

    Raised by :func:`assert_decoded_pixels_within_limit` when the image header
    declares a raster over ``WORKER_MAX_DECODED_PIXELS``. Terminal — the job is
    failed, never retried, and the bytes are never fully decoded.
    """


def decoded_pixel_count(source: bytes) -> int:
    """Return ``width × height`` from *source*'s header without decoding pixels.

    ``Image.open`` parses just enough of the header to expose ``size``; it does
    not call ``load()``, so no raster is allocated. A non-image / corrupt header
    raises (``UnidentifiedImageError`` / ``OSError``) and is treated as a render
    failure by the caller.
    """
    with Image.open(io.BytesIO(source)) as image:
        width, height = image.size
    return width * height


def assert_decoded_pixels_within_limit(source: bytes, config: WorkerConfig) -> None:
    """Refuse a decompression-bomb source before the full decode (P1.2).

    Inspects only the header, so a bomb costs no raster allocation. Raises
    :class:`DecodedImageTooLargeError` when the declared pixel count exceeds
    ``WORKER_MAX_DECODED_PIXELS``.
    """
    pixels = decoded_pixel_count(source)
    if pixels > config.WORKER_MAX_DECODED_PIXELS:
        raise DecodedImageTooLargeError(
            f"source image decodes to {pixels} pixels, exceeding the worker "
            f"ceiling of {config.WORKER_MAX_DECODED_PIXELS}"
        )
