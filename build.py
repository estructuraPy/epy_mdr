"""Build the epy_reports application bundle for the installer.

Run from the project root:

    python build.py              # build dist/epy_reports/ (installer input)

This produces the PyInstaller onedir layout under ``dist/epy_reports/``,
which is the staging folder packaged by the Windows installer
(``src/epy_reports/_core/_packaging/windows/epy_reports.iss``) and the
Linux ``.deb`` builder.
It is an intermediate build artifact, not a distributable app — the
shipped deliverables are the ``setup.exe`` and the ``.deb``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
SPEC = ROOT / "epy_reports.spec"
APP_NAME = "epy_reports"
BUILD_SUPPORT = ROOT / "build_support"


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Run a subprocess and abort with its exit code on failure."""
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, check=False, env=env)
    if result.returncode != 0:
        sys.exit(result.returncode)


def _build_env() -> dict[str, str]:
    """Environment for PyInstaller: prepend the build-support dir.

    ``build_support/sitecustomize.py`` pins the System32 ICU in every
    Python process of the build tree, so PyInstaller's isolated Qt
    introspection can import PySide6 under conda (see that module's
    docstring). Without it the Qt plugin collection fails SILENTLY and
    the frozen app cannot initialize a platform plugin.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{BUILD_SUPPORT}{os.pathsep}{existing}"
        if existing
        else str(BUILD_SUPPORT)
    )
    return env


def _verify_qt_runtime(target: Path) -> None:
    """Fail the build when the Qt runtime is incomplete.

    Guards against the silent-skip failure mode above: a bundle that
    builds "successfully" but cannot start (missing platform plugin) or
    cannot render previews (missing WebEngine helper/resources).
    """
    internal = target / "_internal"
    required = {
        "Qt platform plugin": internal
        / "PySide6"
        / "plugins"
        / "platforms"
        / "qwindows.dll",
        "WebEngine helper": internal / "PySide6" / "QtWebEngineProcess.exe",
        "WebEngine ICU data": internal
        / "PySide6"
        / "resources"
        / "icudtl.dat",
    }
    missing = [
        f"{label}: {path}"
        for label, path in required.items()
        if not path.is_file()
    ]
    poison = [
        str(p)
        for p in internal.rglob("icu*.dll")
        # Any bundled ICU DLL would shadow the System32 one Qt links
        # against on end-user machines (icudtl.dat is fine: data, not a DLL).
    ]
    if missing or poison:
        for line in missing:
            print(f"MISSING  {line}")
        for line in poison:
            print(f"POISON   bundled ICU DLL: {line}")
        sys.exit(
            "Qt runtime verification failed — refusing to ship this bundle."
        )
    print(
        "Qt runtime verified: platform plugin, WebEngine helper "
        "and resources present."
    )


def _clean() -> None:
    """Remove previous build and dist directories."""
    for path in (BUILD, DIST):
        if path.exists():
            print(f"removing {path}")
            shutil.rmtree(path)


def _build_onedir() -> Path:
    """Run PyInstaller via the project spec. Returns the dist folder."""
    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
        env=_build_env(),
    )
    target = DIST / APP_NAME
    if not target.exists():
        sys.exit(f"PyInstaller did not produce {target}")
    _verify_qt_runtime(target)
    return target


def _purge_build_artifacts() -> None:
    """Remove PyInstaller's staging ``build/`` after a successful run.

    ``build/`` is intermediate (cache + warning logs + PYZ slices) and
    only useful for incremental rebuilds. Deleting it after each run
    keeps the project root clean. ``--keep-build`` skips this step
    when you actually want the staging tree for debugging.
    """
    if BUILD.exists():
        print(f"cleaning {BUILD}")
        shutil.rmtree(BUILD, ignore_errors=True)


ISS = (
    ROOT / "src" / APP_NAME / "_core" / "_packaging" / "windows"
    / f"{APP_NAME}.iss"
)


def _package_version() -> str:
    """Return the version the package reports."""
    text = (ROOT / "src" / APP_NAME / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', text)
    if match is None:
        sys.exit(f"No __version__ in {APP_NAME}/__init__.py.")
    return match.group(1)


def _installer_version() -> str:
    """Return the version the installer script declares."""
    if not ISS.is_file():
        sys.exit(f"No installer script at {ISS}.")
    match = re.search(
        r'(?m)^#define\s+AppVersion\s+"([^"]+)"',
        ISS.read_text(encoding="utf-8-sig"),
    )
    if match is None:
        sys.exit(f"No #define AppVersion in {ISS}.")
    return match.group(1)


def _verify_version() -> None:
    """Fail the build when the package and the installer disagree.

    This application installs on its own as well as inside ePy Studio,
    so this installer is a deliverable in its own right and its version
    is what a person reads in Add/Remove. Inno Setup cannot read Python,
    so ``#define AppVersion`` is written by hand and drifts -- measured,
    all three editors had drifted at once. An installer whose file name
    and Add/Remove entry claim a version the executable does not report
    is a support call nobody can answer, so the mismatch fails HERE,
    where it costs one edit.

    Raises:
        SystemExit: Naming both numbers and which file to change.
    """
    package, installer = _package_version(), _installer_version()
    if package != installer:
        sys.exit(
            f"Version mismatch: {APP_NAME}.__version__ is {package} but "
            f"{ISS.name} declares AppVersion {installer}. Update the "
            f"#define and rebuild."
        )
    print(f"Version verified: {package} in both the package and the .iss.")


def main() -> int:
    """CLI entry point for the build script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Skip the initial cleanup of build/ and dist/.",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help=(
            "Do not delete the build/ staging dir after a "
            "successful build (debug only)."
        ),
    )
    args = parser.parse_args()

    _verify_version()
    if not args.keep:
        _clean()

    produced = _build_onedir()

    if not args.keep_build:
        _purge_build_artifacts()

    print(f"\nDone. Installer input: {produced}")
    print(
        "Next: build the installer "
        "(src/epy_reports/_core/_packaging/windows/epy_reports.iss)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
