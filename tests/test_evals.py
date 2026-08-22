import json
import tempfile
from pathlib import Path

from evals.run import load_tasks, score, _tools_from_log


def task(**kw):
    base = {
        "id": "t1",
        "prompt": "p",
        "expect_tools": [],
        "expect_substrings": [],
        "forbid_tools": [],
    }
    base.update(kw)
    return base


def test_passes_when_expected_tool_ran_and_substring_present():
    result = score(
        task(expect_tools=["list_dir"], expect_substrings=["files"]),
        answer="You have 3 files.",
        tools_used=["list_dir"],
    )
    assert result["passed"] is True
    assert result["missing_tools"] == []


def test_fails_when_expected_tool_missing():
    result = score(
        task(expect_tools=["list_dir"]), answer="whatever", tools_used=[]
    )
    assert result["passed"] is False
    assert result["missing_tools"] == ["list_dir"]


def test_fails_when_substring_absent():
    result = score(
        task(expect_substrings=["calculator"]), answer="I opened Notes.", tools_used=[]
    )
    assert result["passed"] is False
    assert result["missing_substrings"] == ["calculator"]


def test_fails_when_forbidden_tool_ran():
    result = score(
        task(forbid_tools=["send_mail"]), answer="ok", tools_used=["send_mail"]
    )
    assert result["passed"] is False
    assert result["forbidden_used"] == ["send_mail"]


def test_substring_match_is_case_insensitive():
    result = score(task(expect_substrings=["CALCULATOR"]), answer="opened calculator", tools_used=[])
    assert result["passed"] is True


def test_load_tasks_reads_the_shipped_suite():
    tasks = load_tasks("evals/tasks.yaml")
    assert len(tasks) >= 8
    for t in tasks:
        assert t["id"] and t["prompt"]


class TestToolsFromLog:
    """Hermetic tests for ground-truth parser (audit log)."""

    def _make_log(self, records: list[dict]) -> Path:
        """Helper: write JSONL temp file and return path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
            return Path(f.name)

    def test_auto_and_tool_result_yield_tool_once(self):
        """Gate AUTO + loop tool_result both emitted → deduplicate to one tool."""
        path = self._make_log([
            {"tool": "list_dir", "decision": "auto"},  # gate record
            {"event": "tool_result", "tool": "list_dir", "status": "ok"},  # loop record
        ])
        try:
            result = _tools_from_log(path, 0)
            assert result == ["list_dir"]  # deduplicated: appears once
        finally:
            path.unlink()

    def test_denied_tool_yields_nothing(self):
        """A gate record with decision=denied → tool NOT counted as used."""
        path = self._make_log([
            {"tool": "send_mail", "decision": "denied"},  # user refused
        ])
        try:
            result = _tools_from_log(path, 0)
            assert result == []  # security: attempted but denied is NOT used
        finally:
            path.unlink()

    def test_refused_tool_yields_nothing(self):
        """A gate record with decision=refused (NEVER tier) → tool NOT counted."""
        path = self._make_log([
            {"tool": "delete_file", "decision": "refused"},  # NEVER tier
        ])
        try:
            result = _tools_from_log(path, 0)
            assert result == []
        finally:
            path.unlink()

    def test_confirmed_tool_is_included(self):
        """A gate record with decision=confirmed (user approved) → counted."""
        path = self._make_log([
            {"tool": "send_mail", "decision": "confirmed"},  # user approved
        ])
        try:
            result = _tools_from_log(path, 0)
            assert result == ["send_mail"]
        finally:
            path.unlink()

    def test_malformed_lines_are_skipped(self):
        """Non-JSON lines don't crash; are silently skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not json\n")
            f.write(json.dumps({"tool": "list_dir", "decision": "auto"}) + "\n")
            f.write("also not json\n")
            path = Path(f.name)
        try:
            result = _tools_from_log(path, 0)
            assert result == ["list_dir"]
        finally:
            path.unlink()

    def test_since_offset_skips_early_records(self):
        """since parameter skips initial N lines."""
        path = self._make_log([
            {"tool": "list_dir", "decision": "auto"},  # line 0
            {"tool": "read_file", "decision": "auto"},  # line 1
            {"tool": "send_mail", "decision": "auto"},  # line 2
        ])
        try:
            # Skip first 2 lines, process only line 2
            result = _tools_from_log(path, 2)
            assert result == ["send_mail"]
        finally:
            path.unlink()

    def test_preserves_order_on_deduplicate(self):
        """Deduplication preserves first-seen order."""
        path = self._make_log([
            {"tool": "a", "decision": "auto"},
            {"event": "tool_result", "tool": "a", "status": "ok"},  # duplicate
            {"tool": "b", "decision": "auto"},
            {"tool": "a", "decision": "auto"},  # duplicate again
        ])
        try:
            result = _tools_from_log(path, 0)
            assert result == ["a", "b"]  # a appears once, in first-seen position
        finally:
            path.unlink()

    def test_nonexistent_log_returns_empty(self):
        """Missing log file → empty list (not an error)."""
        result = _tools_from_log(Path("/nonexistent/file.jsonl"), 0)
        assert result == []
