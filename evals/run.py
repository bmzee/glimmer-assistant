"""Offline-scored eval harness. Drives the real agent loop against any
OpenAI-compatible endpoint so two models can be A/B'd by swapping one value.

Run:  .venv/bin/python -m evals.run --model muse-glimmer:30b --out results.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml


def load_tasks(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text()) or []
    for task in data:
        task.setdefault("expect_tools", [])
        task.setdefault("expect_substrings", [])
        task.setdefault("forbid_tools", [])
    return data


def score(task: dict, answer: str, tools_used: list[str]) -> dict:
    lowered = (answer or "").lower()
    missing_tools = [t for t in task["expect_tools"] if t not in tools_used]
    missing_substrings = [
        s for s in task["expect_substrings"] if s.lower() not in lowered
    ]
    forbidden_used = [t for t in task["forbid_tools"] if t in tools_used]
    return {
        "id": task["id"],
        "passed": not (missing_tools or missing_substrings or forbidden_used),
        "missing_tools": missing_tools,
        "missing_substrings": missing_substrings,
        "forbidden_used": forbidden_used,
        "answer": answer,
        "tools_used": tools_used,
    }


def _tools_from_log(log_path: Path, since: int) -> list[str]:
    """Ground truth: which tools actually executed, from the audit log."""
    if not log_path.exists():
        return []
    lines = log_path.read_text().splitlines()[since:]
    used = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = record.get("tool")
        if name and record.get("decision") in (None, "auto", "confirmed"):
            used.append(name)
    return used


def run_task(task: dict, loop, log_path: Path) -> dict:
    before = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    start = time.time()
    try:
        answer = loop.run(task["prompt"])
    except Exception as e:  # a crash is a failed task, not a crashed run
        answer = f"ERROR: {e}"
    elapsed = time.time() - start
    result = score(task, answer, _tools_from_log(log_path, before))
    result["seconds"] = round(elapsed, 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", default="evals/tasks.yaml")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from assistant.config import load_config
    from assistant.main import build_loop

    cfg = load_config(None)
    cfg.llm_model = args.model
    log_path = Path(cfg.log_path).expanduser()

    # Evals must be non-interactive: auto-decline every confirmation, so a
    # Tier-2 tool can never fire unattended during a benchmark run.
    loop = build_loop(cfg, lambda request: False, "darwin")

    results = [run_task(t, loop, log_path) for t in load_tasks(args.tasks)]
    passed = sum(1 for r in results if r["passed"])
    summary = {
        "model": args.model,
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2))
    print(f"\n{args.model}: {passed}/{len(results)} passed")


if __name__ == "__main__":
    main()
