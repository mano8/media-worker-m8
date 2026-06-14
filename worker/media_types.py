"""Image-format → MIME mapping for variant uploads.

``imgtools_m8`` reports an output format name (e.g. ``"JPEG"``, ``"WEBP"``); the
worker needs the matching ``Content-Type`` to store the rendered variant. This is
the worker's only format knowledge — it never inspects or chooses formats, which
the producer (media-service) pins inside each ``VariantSpec.output_options``.
"""

#: Canonical MIME type per imgtools output-format name (upper-cased lookup).
CONTENT_TYPE_BY_FORMAT: dict[str, str] = {
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "AVIF": "image/avif",
}

#: Fallback when a format is unknown — generic binary, never an active type.
DEFAULT_CONTENT_TYPE = "application/octet-stream"


def content_type_for_format(fmt: str) -> str:
    """Return the MIME type for an imgtools format name (case-insensitive)."""
    return CONTENT_TYPE_BY_FORMAT.get(fmt.upper(), DEFAULT_CONTENT_TYPE)
