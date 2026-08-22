from __future__ import annotations

import urllib.request
from pathlib import Path

KOKORO_DIR = Path("~/.cache/glimmer-assistant/kokoro").expanduser()
_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def _download(url: str, dest: Path) -> None:
    import os

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dest)


def ensure_kokoro_models() -> tuple[Path, Path]:
    paths = []
    for name in _FILES:
        dest = KOKORO_DIR / name
        if not (dest.exists() and dest.stat().st_size > 0):
            _download(_BASE + name, dest)
        paths.append(dest)
    return paths[0], paths[1]
