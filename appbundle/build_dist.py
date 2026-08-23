"""Build a self-contained Glimmer Assistant.app (and a .dmg to hand out).

Unlike appbundle/build_app.py -- which writes a launcher that execs your dev
venv, and stops working the moment that venv moves -- this embeds Python and
every dependency, so the app can be dragged to /Applications and run on a
machine that has never seen the repo.

    python -m appbundle.build_dist            # .app
    python -m appbundle.build_dist --dmg      # .app + .dmg

WHAT STILL IS NOT BUNDLED, and why:
  - Ollama and its model. The model alone is ~18 GB and Ollama is its own
    app; no bundler solves that. assistant/preflight.py detects it and tells
    the user what to do.
  - Voice models (~1 GB). Downloaded to ~/.cache on first use, by design.
  - Playwright's Chromium (~150 MB), which lives in ~/Library/Caches and is
    fetched by `playwright install chromium`.

The --collect-all list below is not guesswork: each entry was established by
freezing a probe and running it. In particular `language_tags` and `segments`
are data-only transitive dependencies of phonemizer, and without them
phonemization dies with a FileNotFoundError that names neither package.
"""
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from appbundle.build_app import (
    APPLE_EVENTS_USAGE,
    BUNDLE_ID,
    MIC_USAGE,
    VERSION,
)

APP_NAME = "Glimmer Assistant"

# Verified by freezing and RUNNING a probe, not by reading docs.
COLLECT_ALL = [
    "mlx",              # Metal shaders (.metallib) beside the package
    "parakeet_mlx",
    "onnxruntime",      # native runtime + dylibs
    "kokoro_onnx",
    "espeakng_loader",  # ships libespeak-ng.dylib + espeak-ng-data
    "phonemizer",
    "language_tags",    # data-only; its absence looks like an espeak failure
    "segments",
    "sounddevice",
    "playwright",
]

HIDDEN_IMPORTS = ["assistant", "assistant.bundled"]


def _run(cmd: list[str], desc: str) -> None:
    print(f"[build] {desc}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-2500:]
        raise SystemExit(f"{desc} failed:\n{tail}")


def build_app(dist: Path, work: Path, clean: bool = True) -> Path:
    entry = Path(__file__).parent / "_entry.py"
    entry.write_text(
        '"""Generated PyInstaller entry point. Do not edit."""\n'
        "from assistant.bundled import main\n\n"
        "raise SystemExit(main())\n"
    )

    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--windowed",                       # produces a .app
        "--name", APP_NAME,
        "--osx-bundle-identifier", BUNDLE_ID,
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(Path.cwd()),
    ]
    if clean:
        cmd.append("--clean")
    for pkg in COLLECT_ALL:
        cmd += ["--collect-all", pkg]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    cmd.append(str(entry))

    _run(cmd, "PyInstaller bundle")
    app = dist / f"{APP_NAME}.app"
    if not app.is_dir():
        raise SystemExit(f"expected {app}, PyInstaller produced nothing")
    return app


def patch_plist(app: Path) -> None:
    """PyInstaller writes a minimal Info.plist; add what TCC requires.

    Without the usage strings macOS kills the process instead of prompting,
    so this is not cosmetic.
    """
    path = app / "Contents" / "Info.plist"
    info = plistlib.loads(path.read_bytes())
    info.update({
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        # NOT LSUIElement. That was right for the menu-bar design and is wrong
        # now: a background agent cannot reliably surface a TCC prompt, because
        # those need a foreground app context -- so the microphone dialog never
        # appeared and recording silently captured nothing. It also contradicts
        # the window's NSApplicationActivationPolicyRegular. A Dock icon is a
        # feature here: it is how you find the app and quit it.
        "LSUIElement": False,
        "NSMicrophoneUsageDescription": MIC_USAGE,
        "NSAppleEventsUsageDescription": APPLE_EVENTS_USAGE,
        "NSHighResolutionCapable": True,
    })
    path.write_bytes(plistlib.dumps(info))
    print(f"[build] patched Info.plist ({BUNDLE_ID})")


def sign(app: Path) -> None:
    """Ad-hoc sign so TCC has a stable identity to bind grants to.

    Unsigned bundles have their grants invalidated whenever the executable
    changes, which the user experiences as permissions randomly needing to be
    re-granted.

    Deliberately WITHOUT `--options runtime`. Hardened runtime enables library
    validation, and a PyInstaller bundle loads an embedded Python.framework
    that was signed separately. Two independently ad-hoc-signed binaries have
    no Team ID to match on, so validation rejects the framework and the app
    dies before running a line of Python:

        Failed to load Python shared library ... Contents/Frameworks/Python
        ... (non-platform) have different Team IDs

    Hardened runtime is a notarization requirement, and notarization needs a
    Developer ID certificate -- which an ad-hoc build does not have. Adding the
    flag here buys nothing and breaks the app. Re-introduce it only together
    with a real signing identity; see docs/packaging.md.
    """
    if not shutil.which("codesign"):
        print("[build] codesign not found; leaving unsigned")
        return
    _run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        "ad-hoc signing",
    )


def build_dmg(app: Path, dist: Path) -> Path:
    """A drag-to-Applications disk image, which is how Mac apps are handed out."""
    if not shutil.which("hdiutil"):
        raise SystemExit("hdiutil not found; cannot build a .dmg")
    staging = dist / "dmg"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")

    dmg = dist / f"{APP_NAME}.dmg"
    dmg.unlink(missing_ok=True)
    _run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging),
         "-ov", "-format", "UDZO", str(dmg)],
        "disk image",
    )
    shutil.rmtree(staging, ignore_errors=True)
    return dmg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--dmg", action="store_true", help="also build a .dmg")
    parser.add_argument("--no-sign", action="store_true")
    parser.add_argument("--no-clean", action="store_true")
    ns = parser.parse_args(argv)

    dist = Path(ns.dist).expanduser().resolve()
    work = dist / "build"
    dist.mkdir(parents=True, exist_ok=True)

    app = build_app(dist, work, clean=not ns.no_clean)
    patch_plist(app)
    if not ns.no_sign:
        sign(app)

    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"\nbuilt {app}  ({size / 1e9:.2f} GB)")

    if ns.dmg:
        dmg = build_dmg(app, dist)
        print(f"built {dmg}  ({dmg.stat().st_size / 1e9:.2f} GB)")

    print("\nInstall:  drag the app to /Applications, then open it once.")
    print("Grant Microphone and Automation under System Settings >")
    print("Privacy & Security. It needs Ollama running -- the app will say so")
    print("if it is missing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
