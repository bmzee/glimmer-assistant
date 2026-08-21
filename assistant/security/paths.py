from __future__ import annotations

from pathlib import Path


class PathNotAllowedError(Exception):
    pass


def resolve_safe(path_str: str, allowed_roots: list[Path]) -> Path:
    p = Path(path_str).expanduser().resolve()
    for root in allowed_roots:
        r = Path(root).expanduser().resolve()
        if p == r or r in p.parents:
            return p
    raise PathNotAllowedError(f"path outside allowed roots: {p}")
