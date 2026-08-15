"""Changelog/version parity — A32-changelog-version-parity.

`fa-auth-m8` shipped `2.0.1`/`2.0.2`, `auth-sdk-m8` shipped `3.1.1`/`3.1.2`, and
`imgtools_m8` shipped `2.1.0` — all tagged and released with no matching
`CHANGELOG.md` entry. This locks the fix in place for `media-worker-m8`: the
current package version must head a changelog entry, and no two entries may
claim the same version, so the next release cannot ship undocumented.
"""

import re
from pathlib import Path

from worker import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_HEADING_RE = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\]", re.MULTILINE)


def test_changelog_exists() -> None:
    assert CHANGELOG.exists(), "CHANGELOG.md must exist at the repo root."


def test_current_version_has_a_changelog_entry() -> None:
    """The version in `worker.__version__` must head a CHANGELOG entry."""
    headings = _HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
    assert __version__ in headings, (
        f"CHANGELOG.md has no '## [{__version__}]' heading for the current "
        f"version (worker.__version__ = {__version__!r}); every published "
        "version must be documented."
    )


def test_changelog_headings_are_unique() -> None:
    """No two entries may claim the same version (the imgtools_m8 A32 finding)."""
    headings = _HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
    duplicates = {v for v in headings if headings.count(v) > 1}
    assert not duplicates, (
        f"CHANGELOG.md has duplicate '## [x.y.z]' headings for: {sorted(duplicates)}"
    )
