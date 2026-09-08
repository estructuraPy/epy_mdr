"""The application's version is one number, in files that must agree.

``pyproject.toml`` takes it dynamically from ``__version__``, so those
two cannot drift. The Inno Setup script can: it carries its own
``#define AppVersion``, and ``build.py`` refuses when the two disagree.

That refusal runs only in a BUILD. Measured on 2026-09-08: the release
gate here was green -- ruff, the whole test suite, housekeeper and
pyright -- the tag was pushed, and the installer pipeline was the first
thing to say the number had been bumped in one file out of two. A check
the local gate cannot run is a check that reports after the release.
"""

from __future__ import annotations

import re
from pathlib import Path

import epy_reports

ROOT = Path(__file__).resolve().parents[1]
ISS = (
    ROOT / "src" / "epy_reports" / "_core" / "_packaging" / "windows"
    / "epy_reports.iss"
)


def _installer_version() -> str:
    """Return the version the Windows installer script declares."""
    text = ISS.read_text(encoding="utf-8-sig")
    match = re.search(r'^#define\s+AppVersion\s+"([^"]+)"', text, re.M)
    assert match, f"{ISS.name} declares no AppVersion"
    return match.group(1)


def test_the_installer_declares_the_same_version() -> None:
    assert epy_reports.__version__ == _installer_version()


def test_it_is_a_release_number() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", epy_reports.__version__)


def test_the_changelog_has_a_heading_for_it() -> None:
    # A tag whose changelog says "Unreleased" is a release nobody can
    # read the notes for.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{epy_reports.__version__}]" in changelog
