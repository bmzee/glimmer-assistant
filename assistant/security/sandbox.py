from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


class SandboxUnavailable(Exception):
    pass


def sandbox_available() -> bool:
    return sys.platform == "darwin" and Path(_SANDBOX_EXEC).exists()


def build_profile(writable_roots: list[Path]) -> str:
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow file-read*)",
        "(allow sysctl-read)",
    ]
    for root in writable_roots:
        resolved = Path(root).expanduser().resolve()
        resolved_str = str(resolved)
        # Reject paths with unsafe characters that could break SBPL string literals
        if '"' in resolved_str or '\\' in resolved_str or '\n' in resolved_str:
            raise ValueError(f"unsafe character in sandbox writable root: {resolved!r}")
        lines.append(f'(allow file-write* (subpath "{resolved}"))')
    return "\n".join(lines) + "\n"


def wrap_command(argv: list[str], writable_roots: list[Path]) -> list[str]:
    if not sandbox_available():
        raise SandboxUnavailable("sandbox-exec is not available on this platform")
    profile = build_profile(writable_roots)
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".sb", prefix="glimmer-sandbox-", delete=False
    )
    handle.write(profile)
    handle.close()
    return [_SANDBOX_EXEC, "-f", handle.name, *argv]
