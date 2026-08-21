from __future__ import annotations

import datetime
import json
from pathlib import Path


class ActionLog:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        entry = {"ts": datetime.datetime.now(datetime.UTC).isoformat(), **record}
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
