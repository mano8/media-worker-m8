"""Static compose-policy tests for image pinning (item 4.1).

These tests parse docker_compose/docker-compose.yml directly — no running
Docker required.

Policy:
  clamav — must be pinned to an explicit versioned tag (no bare name, no
  :latest). Digest pinning is the recommended production upgrade path but is
  not required by this suite (the minimum bar is a stable version tag).

  worker — built locally from source; must not carry a floating image:
  reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_COMPOSE = Path(__file__).parent.parent / "docker_compose" / "docker-compose.yml"

_BARE_IMAGE_RE = re.compile(r"^[^:@]+$")
_LATEST_RE = re.compile(r":latest$", re.IGNORECASE)


def _load() -> dict:
    return yaml.safe_load(_COMPOSE.read_text())


def _service_images(compose: dict) -> list[tuple[str, str]]:
    """Return [(service_name, image_ref), ...] for every service that sets image:."""
    return [
        (name, svc["image"])
        for name, svc in compose.get("services", {}).items()
        if "image" in svc
    ]


class TestWorkerComposePins:
    """Image-pin policy for docker_compose/docker-compose.yml."""

    def _images(self) -> list[tuple[str, str]]:
        return _service_images(_load())

    def test_no_bare_images(self):
        bare = [(s, i) for s, i in self._images() if _BARE_IMAGE_RE.match(i)]
        assert not bare, (
            "docker-compose.yml: bare (untagged) image references — "
            "pin each to a specific tag or digest:\n"
            + "\n".join(f"  {s}: {i}" for s, i in bare)
        )

    def test_no_latest_tag(self):
        latest = [(s, i) for s, i in self._images() if _LATEST_RE.search(i)]
        assert not latest, (
            "docker-compose.yml: :latest tags found — "
            "pin to an immutable tag or digest:\n"
            + "\n".join(f"  {s}: {i}" for s, i in latest)
        )

    def test_clamav_pinned_to_versioned_tag(self):
        images = dict(self._images())
        img = images.get("clamav")
        assert img is not None, "clamav service not found in docker-compose.yml"
        assert img.startswith("clamav/clamav:"), (
            f"clamav image {img!r} must start with 'clamav/clamav:' — "
            "was the image reference changed?"
        )

    def test_worker_service_is_build_only(self):
        compose = _load()
        svc = compose.get("services", {}).get("worker", {})
        assert "build" in svc, "worker service must define a build: context"
        assert "image" not in svc, (
            "worker service must not carry a floating image: reference — "
            "it is always built locally from source"
        )
