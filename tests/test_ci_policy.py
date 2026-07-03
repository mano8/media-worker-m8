"""CI workflow and Dockerfile policy tests — finding 11.5.

Asserts that the publish pipeline emits a verifiable supply-chain artefact set
and that the Dockerfile resolves to a fixed, digest-pinned base layer.

Rules asserted here (11.5):
- worker/Dockerfile must use a digest-pinned FROM (@sha256:...) in both the
  builder and runtime stages so rebuilds cannot silently resolve a changed layer.
- docker-publish.yaml must declare ``id-token: write`` (OIDC) and
  ``attestations: write`` (GitHub provenance) permissions.
- docker-publish.yaml must invoke ``anchore/sbom-action`` to generate an SBOM.
- docker-publish.yaml must build with ``provenance: mode=max`` so the published
  image carries an in-toto provenance attestation.
- docker-publish.yaml must sign the published image digest with ``cosign sign``.
- Every ``uses:`` reference in docker-publish.yaml must be pinned to a full
  40-char commit SHA (immutable action reference).

Notes:
- 11.7 invariants (no duplicate ci.yml, secret-scan job, CI.yaml action pins)
  are added to this file when that phase ships.
- No Docker or network access is required to run these tests.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "worker"
DOCKERFILE = WORKER / "Dockerfile"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DOCKER_PUBLISH_YAML = WORKFLOWS / "docker-publish.yaml"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USES_RE = re.compile(r"uses:\s+([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+@(\S+))")
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}")


def _action_refs(path: Path) -> list[tuple[str, str]]:
    """Return (full-ref, sha-candidate) for every action ``uses:`` in a workflow."""
    results: list[tuple[str, str]] = []
    for m in _USES_RE.finditer(path.read_text()):
        full_ref = m.group(1)
        sha_part = m.group(2).split("#")[0].strip()
        results.append((full_ref, sha_part))
    return results


# ---------------------------------------------------------------------------
# 11.5 — Dockerfile digest pinning
# ---------------------------------------------------------------------------


def test_dockerfile_from_stages_are_digest_pinned() -> None:
    """Both FROM stages in worker/Dockerfile must use @sha256: digests."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    from_lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith("FROM")
    ]
    assert from_lines, "No FROM lines found in Dockerfile"
    for line in from_lines:
        assert _DIGEST_RE.search(line), (
            f"Dockerfile FROM line is not digest-pinned: '{line}' — "
            "add @sha256:<digest> so rebuilds cannot silently resolve a different base layer"
        )


# ---------------------------------------------------------------------------
# 11.5 — Publish workflow supply-chain attestations
# ---------------------------------------------------------------------------


def test_publish_has_oidc_permission() -> None:
    """docker-publish.yaml must grant ``id-token: write`` for keyless OIDC signing."""
    text = DOCKER_PUBLISH_YAML.read_text()
    assert "id-token: write" in text, (
        "docker-publish.yaml is missing 'id-token: write' — required for keyless cosign OIDC."
    )


def test_publish_has_attestations_permission() -> None:
    """docker-publish.yaml must grant ``attestations: write`` for GitHub provenance."""
    text = DOCKER_PUBLISH_YAML.read_text()
    assert "attestations: write" in text, (
        "docker-publish.yaml is missing 'attestations: write' — required for GitHub artifact attestations."
    )


def test_publish_generates_sbom() -> None:
    """docker-publish.yaml must invoke anchore/sbom-action to generate an SBOM."""
    text = DOCKER_PUBLISH_YAML.read_text()
    assert "anchore/sbom-action" in text, (
        "docker-publish.yaml does not call anchore/sbom-action — SBOM generation is required."
    )


def test_publish_pushes_with_provenance_mode_max() -> None:
    """docker-publish.yaml must set ``provenance: mode=max`` on the build-push step."""
    text = DOCKER_PUBLISH_YAML.read_text()
    assert "provenance: mode=max" in text, (
        "docker-publish.yaml build-push step is missing 'provenance: mode=max' — "
        "in-toto provenance attestation requires mode=max."
    )


def test_publish_signs_with_cosign() -> None:
    """docker-publish.yaml must sign the published image digest with cosign."""
    text = DOCKER_PUBLISH_YAML.read_text()
    assert "cosign sign" in text, (
        "docker-publish.yaml does not invoke 'cosign sign' — keyless image signing is required."
    )


def test_docker_publish_yaml_actions_are_sha_pinned() -> None:
    """Every action reference in docker-publish.yaml must be pinned to a full 40-char SHA."""
    refs = _action_refs(DOCKER_PUBLISH_YAML)
    assert refs, "No action references found in docker-publish.yaml."
    for full_ref, sha_part in refs:
        assert _SHA_RE.match(sha_part), (
            f"docker-publish.yaml: '{full_ref}' is not SHA-pinned — use a full 40-char commit hash."
        )
