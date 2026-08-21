from __future__ import annotations

import subprocess

from assistant.tools.adapters.base import PlatformAdapter


class MacAdapter(PlatformAdapter):
    def launch_app(self, name: str) -> str:
        result = subprocess.run(["open", "-a", name], capture_output=True, text=True)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip() or f'could not open app {name}'}"
        return f"launched {name}"

    def open_path(self, path: str) -> str:
        result = subprocess.run(["open", path], capture_output=True, text=True)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip() or f'could not open {path}'}"
        return f"opened {path}"
