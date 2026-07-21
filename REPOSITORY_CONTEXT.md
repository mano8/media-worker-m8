# media-worker-m8

## Layer

Service (async media processing worker).

## Purpose

Run ARQ background jobs:

- `scan_object` performs antivirus scanning through a pluggable `Scanner`
  interface.
- `generate_variants` generates image variants through the `imgtools_m8` async
  API.

## Responsibilities

- Consume `ScanJobPayload` and `VariantJobPayload` from `media-sdk-m8`.
- Delegate image computation to `imgtools_m8`, the sole imgtools consumer.
- Report results to `media-service-m8` over its internal HTTP API with a Bearer
  service token.

## Repository boundaries

- Remain async-only (`asyncio`/ARQ); wrap synchronous MinIO calls in
  `asyncio.to_thread`.
- Do not depend directly on other services or access another service's database.
- Use `media-sdk-m8` for the storage client and job contracts.
- Communicate across services only through contracts or HTTP APIs.
- Keep `imgtools_m8` worker-only: `media-service-m8` and `media-sdk-m8` must
  never import it.

## Standalone authority

This file, repository documentation, and existing CI are the authoritative local
context. A verified nearest workspace may optionally add launcher-selected
policies and tasks; its absence is a successful standalone condition and does
not make a parent workspace necessary.
