# media-worker-m8

## Layer
Service (async media processing worker)

---

## Purpose
ARQ async worker for background media jobs:
- `scan_object` - antivirus scan (ClamAV) behind a pluggable `Scanner` interface
- `generate_variants` - image variants via the imgtools_m8 async API

---

## Responsibilities
- consume ARQ jobs (`ScanJobPayload` / `VariantJobPayload` from media-sdk-m8)
- delegate image computation to imgtools_m8 (the sole imgtools consumer)
- report results to media-service-m8 over its internal HTTP API (Bearer service token)

---

## Rules
- Async only (asyncio / ARQ); wrap sync MinIO calls in `asyncio.to_thread`
- No direct dependency on other services; no cross-service DB access
- Must use media-sdk-m8 for the storage client and job contracts
- All cross-service communication via contracts or HTTP APIs
- imgtools_m8 is worker-only - media-service-m8 and media-sdk-m8 never import it
---

## Authority
All rules come from /.Codex/policy.index.json (type: python)


