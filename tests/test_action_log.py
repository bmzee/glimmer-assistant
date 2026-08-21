import json
from pathlib import Path

from assistant.security.log import ActionLog


def test_appends_jsonl_with_timestamp(tmp_path: Path):
    log = ActionLog(tmp_path / "sub" / "actions.jsonl")
    log.append({"tool": "list_dir", "decision": "auto"})
    log.append({"tool": "send_mail", "decision": "denied"})

    lines = (tmp_path / "sub" / "actions.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool"] == "list_dir"
    assert first["decision"] == "auto"
    assert "ts" in first and first["ts"].startswith("20")
