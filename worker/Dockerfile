# ---------- BUILD STAGE ----------
FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83 AS builder

WORKDIR /install

ARG ENVIRONMENT=prod
ENV PIP_ROOT_USER_ACTION=ignore

COPY ./worker/requirements_base.txt .
COPY ./worker/requirements_dev.txt .
COPY ./worker/requirements_prod.txt .
COPY ./worker/requirements_prod.lock .

# Release images install from a hash-locked, fully pinned dependency set so a
# rebuild of the same source cannot silently resolve a different graph
# (finding 11.8). `--require-hashes` is enforced for every non-development
# build. Regenerate the lock with:
#   pip-compile --generate-hashes --no-emit-index-url \
#     --output-file=requirements_prod.lock requirements_prod.txt
RUN pip install --upgrade "pip==26.1.1" && \
    if [ "$ENVIRONMENT" = "development" ]; then \
        pip install --prefix=/install --no-cache-dir -r requirements_base.txt && \
        pip install --prefix=/install --no-cache-dir -r requirements_dev.txt ; \
    else \
        pip install --prefix=/install --no-cache-dir \
            --require-hashes -r requirements_prod.lock ; \
    fi


# ---------- RUNTIME STAGE ----------
FROM python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt

# No ClamAV binary or virus database is bundled — the worker is a thin clamd
# *client* and reaches the daemon owned by the `clamav` compose service over TCP.

# Patch OpenSSL packages to the fixed version (CVE-2026-45447 — heap UAF in
# PKCS7_verify; fixed in 3.5.6-1~deb13u2, not yet in the pinned base image).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssl=3.5.6-1~deb13u2 \
        libssl3t64=3.5.6-1~deb13u2 \
        openssl-provider-legacy=3.5.6-1~deb13u2 && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home appuser

WORKDIR /opt

COPY --from=builder /install /usr/local

# Strip the installer tooling from the runtime image. The entrypoint is `arq`;
# this image is built from a hash-locked set and never installs anything at run
# time, so pip, setuptools and wheel are pure attack surface. They are also the
# only remaining Trivy findings — the base image bundles `setuptools 70.3.0`
# (CVE-2025-47273) — and removing them ends that class of finding instead of
# re-chasing a setuptools pin on every base-image bump.
#
# Ordered after the COPY above so the builder's tree cannot reintroduce them,
# and pip uninstalls itself last because the earlier uninstalls need it.
# The import check is the guard: it fails the build if any runtime dependency
# actually needed `pkg_resources`/`setuptools` at import time.
RUN python -m pip uninstall -y setuptools wheel &&     python -m pip uninstall -y pip &&     python -c "import arq, clamd, httpx, minio, pydantic, PIL, media_sdk_m8, imgtools_m8"

COPY --chown=appuser:appuser ./worker ./worker

USER appuser

# ARQ worker process — consumes scan_object / generate_variants /
# build_export_archive from media Redis.
CMD ["arq", "worker.settings.WorkerSettings"]
