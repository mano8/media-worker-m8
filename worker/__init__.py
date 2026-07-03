"""media-worker-m8 — async ARQ worker for background media jobs.

Runs two tasks consumed from the media-owned Redis queue:

* ``scan_object`` — antivirus scan (ClamAV) behind a pluggable ``Scanner``.
* ``generate_variants`` — image variants via the ``imgtools_m8`` async API.

The worker is the sole ``imgtools_m8`` consumer. It owns no database; it reports
results to media-service-m8 over its internal HTTP API (Bearer service token) and
reads/writes object bytes through the shared ``media_sdk_m8`` storage client.
"""

__version__ = "0.3.0"
