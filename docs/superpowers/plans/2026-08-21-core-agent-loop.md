# Core Agent Loop Implementation Plan (Plan 1 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working text-mode assistant: typed request → Muse-Glimmer-30B via Ollama → permission-gated tool calls (files, apps) → answer. The foundation every later phase (security hardening, voice, integrations, evals) builds on.

**Architecture:** Single Python package `assistant`. A hand-rolled tool-calling loop talks to any OpenAI-compatible endpoint (Ollama by default). Tools are declarative `Tool` records in a registry with platform and risk-tier flags; a `PermissionGate` (backed by a JSONL `ActionLog`) authorizes every call; OS-specific work goes through a `PlatformAdapter` (Mac now, Windows later, `FakeAdapter` in tests).

**Tech Stack:** Python ≥3.12, `openai` SDK (pointed at Ollama), `pyyaml`, `pytest`. No agent framework.

**Spec:** `docs/spec.md` (this plan implements §2 partially, §3, §4, §6 partially, §7 partially, §8.3/§8.4/§8.5 partially — see Plan sequence below for what lands later).

## Plan sequence (later plans, written after this one ships)

2. **Security hardening** — `sandbox-exec` wrapper, `run_shell` tool (blocked until sandbox exists per spec §8.1), untrusted-content quarantine/datamarking, undo-window UX for Tier 1, post-action verification (`agent/verify.py`).
3. **Voice pipeline** — pynput PTT, sounddevice + Silero VAD, Parakeet-TDT STT, Kokoro-82M TTS.
4. **Integrations** — Playwright web tools (a11y-tree snapshots), embedded MCP client + pinned servers, MS Graph device-code, Apple Mail/Calendar, AXUIElement reader.
5. **Evals & context** — `evals/tasks.yaml` 10-task suite, Glimmer vs Qwen3.8-27B A/B, structured-output gate on Ollama MLX engine, context compaction at ~65%.

## Global Constraints

- Python ≥ 3.12; package name `assistant`; project root `/Users/bmz/development/perso/glimmer-assistant`.
- Runtime dependencies limited to: `openai>=1.50`, `pyyaml>=6.0`. Dev: `pytest>=8.0`. Nothing else without a spec change.
- Tests never hit the network or a real LLM; LLM interactions are tested with fakes.
- Tests never mutate real user files; all filesystem tests use pytest `tmp_path`.
- Every individual tool result is truncated to `tool_result_max_chars` (default 16000 chars ≈ 4K tokens) per spec §6.
- Every filesystem path from model output goes through `resolve_safe()` (spec §8.4); every tool execution is logged to JSONL (spec §8.5); every tool declares `platforms` and `risk_tier` (spec §7).
- Default endpoint `http://localhost:11434/v1`, model `muse-glimmer:30b` — config values, never hard-coded at call sites.
- Commit after every green test cycle. Run tests with `python -m pytest` from the project root.

---

### Task 1: Project scaffold and config loader

**Files:**
- Create: `pyproject.toml`
- Create: `assistant/__init__.py` (empty)
- Create: `assistant/config.py`
- Create: `assistant/config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Config` dataclass with fields `llm_base_url: str`, `llm_model: str`, `llm_api_key: str`, `max_iterations: int`, `tool_result_max_chars: int`, `allowed_roots: list[str]`, `log_path: str`; and `load_config(path: str | Path | None = None) -> Config`.

- [ ] **Step 1: Write pyproject and package skeleton**

`pyproject.toml`:

```toml
[project]
name = "glimmer-assistant"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["openai>=1.50", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create empty `assistant/__init__.py`. Create the venv and install:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Use `.venv/bin/python -m pytest` for every test run in this plan.

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:

```python
from pathlib import Path

from assistant.config import Config, load_config


def test_defaults_without_file():
    cfg = load_config(None)
    assert cfg.llm_base_url == "http://localhost:11434/v1"
    assert cfg.llm_model == "muse-glimmer:30b"
    assert cfg.max_iterations == 15
    assert cfg.tool_result_max_chars == 16000
    assert cfg.allowed_roots == ["~"]


def test_yaml_overrides(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("llm_model: qwen3.8:27b\nmax_iterations: 5\n")
    cfg = load_config(f)
    assert cfg.llm_model == "qwen3.8:27b"
    assert cfg.max_iterations == 5
    assert cfg.llm_base_url == "http://localhost:11434/v1"  # untouched default


def test_unknown_keys_ignored(tmp_path: Path):
    f = tmp_path / "config.yaml"
    f.write_text("not_a_real_key: 1\n")
    cfg = load_config(f)
    assert not hasattr(cfg, "not_a_real_key")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'assistant.config'`

- [ ] **Step 4: Write minimal implementation**

`assistant/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "muse-glimmer:30b"
    llm_api_key: str = "ollama"  # Ollama ignores the value but the SDK requires one
    max_iterations: int = 15
    tool_result_max_chars: int = 16000
    allowed_roots: list[str] = field(default_factory=lambda: ["~"])
    log_path: str = "~/.glimmer-assistant/actions.jsonl"


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    if path is None:
        return cfg
    data = yaml.safe_load(Path(path).read_text()) or {}
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg
```

`assistant/config.yaml` (shipped defaults, all commented out so code defaults rule):

```yaml
# llm_base_url: http://localhost:11434/v1
# llm_model: muse-glimmer:30b
# max_iterations: 15
# tool_result_max_chars: 16000
# allowed_roots: ["~"]
# log_path: ~/.glimmer-assistant/actions.jsonl
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml assistant/ tests/test_config.py .gitignore
git commit -m "feat: project scaffold and config loader"
```

(First add a `.gitignore` containing `.venv/`, `__pycache__/`, `*.egg-info/`.)

---

### Task 2: JSONL action log

**Files:**
- Create: `assistant/security/__init__.py` (empty)
- Create: `assistant/security/log.py`
- Test: `tests/test_action_log.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ActionLog(path: str | Path)` with `append(record: dict) -> None`; each line is JSON with an added ISO-8601 UTC `ts` field.

- [ ] **Step 1: Write the failing test**

`tests/test_action_log.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_action_log.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`assistant/security/log.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_action_log.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add assistant/security/ tests/test_action_log.py
git commit -m "feat: JSONL action log"
```

---

### Task 3: Tool record and registry

**Files:**
- Create: `assistant/tools/__init__.py` (empty)
- Create: `assistant/tools/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RiskTier(IntEnum)`: `AUTO = 0`, `UNDO = 1`, `CONFIRM = 2`, `NEVER = 3`.
  - `Tool` frozen dataclass: `name: str`, `description: str`, `parameters: dict` (JSON Schema), `risk_tier: RiskTier`, `platforms: tuple[str, ...]` (values are `sys.platform` strings: `"darwin"`, `"win32"`), `func: Callable[[dict], str]`.
  - `ToolRegistry` with `register(tool: Tool) -> None` (raises `ValueError` on duplicate name), `available(platform: str) -> list[Tool]`, `schemas(platform: str) -> list[dict]` (OpenAI function-tool format), `get(name: str) -> Tool | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_registry.py`:

```python
import pytest

from assistant.tools.registry import RiskTier, Tool, ToolRegistry


def make_tool(name: str, platforms: tuple[str, ...] = ("darwin", "win32")) -> Tool:
    return Tool(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_tier=RiskTier.AUTO,
        platforms=platforms,
        func=lambda args: "ok",
    )


def test_register_and_get():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    assert reg.get("list_dir").name == "list_dir"
    assert reg.get("missing") is None


def test_duplicate_name_rejected():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    with pytest.raises(ValueError):
        reg.register(make_tool("list_dir"))


def test_platform_filtering():
    reg = ToolRegistry()
    reg.register(make_tool("everywhere"))
    reg.register(make_tool("mac_only", platforms=("darwin",)))
    assert {t.name for t in reg.available("darwin")} == {"everywhere", "mac_only"}
    assert {t.name for t in reg.available("win32")} == {"everywhere"}


def test_openai_schema_shape():
    reg = ToolRegistry()
    reg.register(make_tool("list_dir"))
    (schema,) = reg.schemas("darwin")
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "list_dir"
    assert schema["function"]["parameters"]["type"] == "object"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`assistant/tools/registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class RiskTier(IntEnum):
    AUTO = 0     # read-only: runs freely
    UNDO = 1     # low-blast-radius mutation: runs, logged, undoable (undo UX in Plan 2)
    CONFIRM = 2  # blocking confirmation with preview
    NEVER = 3    # hard-coded refusal (spec §8.3 tier 3)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments object
    risk_tier: RiskTier
    platforms: tuple[str, ...]  # sys.platform values: "darwin", "win32"
    func: Callable[[dict], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def available(self, platform: str) -> list[Tool]:
        return [t for t in self._tools.values() if platform in t.platforms]

    def schemas(self, platform: str) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.available(platform)
        ]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_registry.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add assistant/tools/ tests/test_registry.py
git commit -m "feat: tool record and platform-aware registry"
```

---

### Task 4: Permission gate

**Files:**
- Create: `assistant/security/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `ActionLog` (Task 2), `Tool`/`RiskTier` (Task 3).
- Produces: `PermissionGate(log: ActionLog, confirmer: Callable[[str], bool])` with `check(tool: Tool, args: dict) -> bool`. AUTO/UNDO → True; CONFIRM → asks `confirmer(description)`; NEVER → False. Every decision logged with keys `tool`, `args`, `tier`, `decision` (`"auto"`, `"confirmed"`, `"denied"`, `"refused"`).

- [ ] **Step 1: Write the failing test**

`tests/test_gate.py`:

```python
import json
from pathlib import Path

from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool


def make_tool(tier: RiskTier) -> Tool:
    return Tool(
        name="t",
        description="d",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_tier=tier,
        platforms=("darwin",),
        func=lambda args: "ok",
    )


def make_gate(tmp_path: Path, answer: bool):
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda desc: answer)
    return gate, log_path


def decisions(log_path: Path) -> list[str]:
    return [json.loads(l)["decision"] for l in log_path.read_text().splitlines()]


def test_auto_allowed_and_logged(tmp_path):
    gate, log_path = make_gate(tmp_path, answer=False)
    assert gate.check(make_tool(RiskTier.AUTO), {"x": 1}) is True
    assert decisions(log_path) == ["auto"]


def test_undo_allowed(tmp_path):
    gate, _ = make_gate(tmp_path, answer=False)
    assert gate.check(make_tool(RiskTier.UNDO), {}) is True


def test_confirm_respects_answer(tmp_path):
    gate_yes, path_yes = make_gate(tmp_path, answer=True)
    assert gate_yes.check(make_tool(RiskTier.CONFIRM), {}) is True
    assert decisions(path_yes) == ["confirmed"]

    gate_no, path_no = make_gate(tmp_path / "no", answer=False)
    assert gate_no.check(make_tool(RiskTier.CONFIRM), {}) is False
    assert decisions(path_no) == ["denied"]


def test_never_refused_without_asking(tmp_path):
    asked = []
    log_path = tmp_path / "a.jsonl"
    gate = PermissionGate(ActionLog(log_path), confirmer=lambda d: asked.append(d) or True)
    assert gate.check(make_tool(RiskTier.NEVER), {}) is False
    assert asked == []
    assert decisions(log_path) == ["refused"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`assistant/security/gate.py`:

```python
from __future__ import annotations

from typing import Callable

from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool


class PermissionGate:
    def __init__(self, log: ActionLog, confirmer: Callable[[str], bool]):
        self._log = log
        self._confirmer = confirmer

    def check(self, tool: Tool, args: dict) -> bool:
        tier = tool.risk_tier
        if tier == RiskTier.NEVER:
            self._record(tool, args, "refused")
            return False
        if tier == RiskTier.CONFIRM:
            allowed = self._confirmer(f"{tool.name}({args})")
            self._record(tool, args, "confirmed" if allowed else "denied")
            return allowed
        self._record(tool, args, "auto")
        return True

    def _record(self, tool: Tool, args: dict, decision: str) -> None:
        self._log.append(
            {"tool": tool.name, "args": args, "tier": int(tool.risk_tier), "decision": decision}
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gate.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add assistant/security/gate.py tests/test_gate.py
git commit -m "feat: risk-tiered permission gate"
```

---

### Task 5: Safe paths and file tools

**Files:**
- Create: `assistant/security/paths.py`
- Create: `assistant/tools/files.py`
- Test: `tests/test_paths.py`, `tests/test_files_tools.py`

**Interfaces:**
- Consumes: `Tool`, `RiskTier` (Task 3).
- Produces:
  - `PathNotAllowedError(Exception)` and `resolve_safe(path_str: str, allowed_roots: list[Path]) -> Path` in `assistant/security/paths.py` — expands `~`, resolves symlinks/`..`, raises unless the result is inside (or equal to) an allowed root.
  - `make_files_tools(allowed_roots: list[Path]) -> list[Tool]` in `assistant/tools/files.py` returning tools `list_dir` and `read_file`, both `RiskTier.AUTO`, `platforms=("darwin", "win32")`, each with parameter schema `{"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}`.

- [ ] **Step 1: Write the failing paths test**

`tests/test_paths.py`:

```python
from pathlib import Path

import pytest

from assistant.security.paths import PathNotAllowedError, resolve_safe


def test_inside_root_allowed(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    p = resolve_safe(str(tmp_path / "docs"), [tmp_path])
    assert p == (tmp_path / "docs").resolve()


def test_root_itself_allowed(tmp_path: Path):
    assert resolve_safe(str(tmp_path), [tmp_path]) == tmp_path.resolve()


def test_outside_root_rejected(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_safe("/etc/passwd", [tmp_path])


def test_dotdot_escape_rejected(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_safe(str(tmp_path / ".." / ".."), [tmp_path])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement resolve_safe**

`assistant/security/paths.py`:

```python
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
```

- [ ] **Step 4: Run paths test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: 4 PASS

- [ ] **Step 5: Write the failing file-tools test**

`tests/test_files_tools.py`:

```python
from pathlib import Path

import pytest

from assistant.security.paths import PathNotAllowedError
from assistant.tools.files import make_files_tools
from assistant.tools.registry import RiskTier


def by_name(tools):
    return {t.name: t for t in tools}


def test_list_dir(tmp_path: Path):
    (tmp_path / "b.txt").write_text("hi")
    (tmp_path / "adir").mkdir()
    tools = by_name(make_files_tools([tmp_path]))
    out = tools["list_dir"].func({"path": str(tmp_path)})
    assert out == "adir/\nb.txt"


def test_read_file(tmp_path: Path):
    (tmp_path / "b.txt").write_text("hello")
    tools = by_name(make_files_tools([tmp_path]))
    assert tools["read_file"].func({"path": str(tmp_path / "b.txt")}) == "hello"


def test_read_outside_root_raises(tmp_path: Path):
    tools = by_name(make_files_tools([tmp_path]))
    with pytest.raises(PathNotAllowedError):
        tools["read_file"].func({"path": "/etc/passwd"})


def test_tools_are_auto_tier_and_cross_platform(tmp_path: Path):
    for tool in make_files_tools([tmp_path]):
        assert tool.risk_tier == RiskTier.AUTO
        assert tool.platforms == ("darwin", "win32")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_files_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement file tools**

`assistant/tools/files.py`:

```python
from __future__ import annotations

from pathlib import Path

from assistant.security.paths import resolve_safe
from assistant.tools.registry import RiskTier, Tool

_PATH_PARAM = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}


def make_files_tools(allowed_roots: list[Path]) -> list[Tool]:
    def list_dir(args: dict) -> str:
        p = resolve_safe(args["path"], allowed_roots)
        entries = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir())
        return "\n".join(entries) or "(empty)"

    def read_file(args: dict) -> str:
        p = resolve_safe(args["path"], allowed_roots)
        return p.read_text(errors="replace")

    return [
        Tool(
            name="list_dir",
            description="List the entries in a directory. Directories end with '/'.",
            parameters=_PATH_PARAM,
            risk_tier=RiskTier.AUTO,
            platforms=("darwin", "win32"),
            func=list_dir,
        ),
        Tool(
            name="read_file",
            description="Read a text file's contents.",
            parameters=_PATH_PARAM,
            risk_tier=RiskTier.AUTO,
            platforms=("darwin", "win32"),
            func=read_file,
        ),
    ]
```

(Oversized reads are handled by the loop's global truncation in Task 8, per Global Constraints.)

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_files_tools.py -v`
Expected: 4 PASS

- [ ] **Step 9: Commit**

```bash
git add assistant/security/paths.py assistant/tools/files.py tests/test_paths.py tests/test_files_tools.py
git commit -m "feat: path allowlisting and file tools"
```

---

### Task 6: Platform adapter and app tools

**Files:**
- Create: `assistant/tools/adapters/__init__.py` (empty)
- Create: `assistant/tools/adapters/base.py`
- Create: `assistant/tools/adapters/mac.py`
- Create: `assistant/tools/apps.py`
- Test: `tests/test_app_tools.py`

**Interfaces:**
- Consumes: `Tool`, `RiskTier` (Task 3), `resolve_safe` (Task 5).
- Produces:
  - `PlatformAdapter` ABC in `base.py` with abstract methods `launch_app(self, name: str) -> str` and `open_path(self, path: str) -> str`. (Later plans extend this ABC with `quit_app`, `list_windows`, `focus_window`, `set_volume`, `screenshot`, `run_shell` — do NOT add them now.)
  - `MacAdapter(PlatformAdapter)` in `mac.py` using `subprocess.run(["open", ...])`; failures return `"ERROR: ..."` strings, never raise.
  - `make_app_tools(adapter: PlatformAdapter, allowed_roots: list[Path]) -> list[Tool]` in `apps.py` returning `open_app` (RiskTier.UNDO) and `open_path` (RiskTier.UNDO), both `platforms=("darwin", "win32")` — the adapter, not the tool, is what differs per platform.

- [ ] **Step 1: Write the failing test**

`tests/test_app_tools.py`:

```python
from pathlib import Path

from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.apps import make_app_tools
from assistant.tools.registry import RiskTier


class FakeAdapter(PlatformAdapter):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def launch_app(self, name: str) -> str:
        self.calls.append(("launch_app", name))
        return f"launched {name}"

    def open_path(self, path: str) -> str:
        self.calls.append(("open_path", path))
        return f"opened {path}"


def by_name(tools):
    return {t.name: t for t in tools}


def test_open_app_delegates_to_adapter(tmp_path: Path):
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    assert tools["open_app"].func({"name": "Notes"}) == "launched Notes"
    assert adapter.calls == [("launch_app", "Notes")]


def test_open_path_checks_allowlist(tmp_path: Path):
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    result = tools["open_path"].func({"path": "/etc/passwd"})
    assert result.startswith("ERROR:")
    assert adapter.calls == []


def test_open_path_inside_root(tmp_path: Path):
    (tmp_path / "doc.txt").write_text("x")
    adapter = FakeAdapter()
    tools = by_name(make_app_tools(adapter, [tmp_path]))
    out = tools["open_path"].func({"path": str(tmp_path / "doc.txt")})
    assert out.startswith("opened ")
    assert adapter.calls[0][0] == "open_path"


def test_tiers():
    adapter = FakeAdapter()
    for tool in make_app_tools(adapter, []):
        assert tool.risk_tier == RiskTier.UNDO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement adapter base, MacAdapter, and app tools**

`assistant/tools/adapters/base.py`:

```python
from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    @abstractmethod
    def launch_app(self, name: str) -> str: ...

    @abstractmethod
    def open_path(self, path: str) -> str: ...
```

`assistant/tools/adapters/mac.py`:

```python
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
```

`assistant/tools/apps.py`:

```python
from __future__ import annotations

from pathlib import Path

from assistant.security.paths import PathNotAllowedError, resolve_safe
from assistant.tools.adapters.base import PlatformAdapter
from assistant.tools.registry import RiskTier, Tool


def make_app_tools(adapter: PlatformAdapter, allowed_roots: list[Path]) -> list[Tool]:
    def open_app(args: dict) -> str:
        return adapter.launch_app(args["name"])

    def open_path(args: dict) -> str:
        try:
            p = resolve_safe(args["path"], allowed_roots)
        except PathNotAllowedError as e:
            return f"ERROR: {e}"
        return adapter.open_path(str(p))

    return [
        Tool(
            name="open_app",
            description="Launch (or bring to front) an application by name, e.g. 'Notes'.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin", "win32"),
            func=open_app,
        ),
        Tool(
            name="open_path",
            description="Open a file or folder with its default application.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            risk_tier=RiskTier.UNDO,
            platforms=("darwin", "win32"),
            func=open_path,
        ),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app_tools.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add assistant/tools/adapters/ assistant/tools/apps.py tests/test_app_tools.py
git commit -m "feat: platform adapter with Mac implementation and app tools"
```

---

### Task 7: LLM client

**Files:**
- Create: `assistant/llm/__init__.py` (empty)
- Create: `assistant/llm/client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces: `LLMClient(cfg: Config, client=None)` — when `client` is None, builds `openai.OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)`; `chat(messages: list[dict], tools: list[dict])` returns the SDK message object (`response.choices[0].message`, which has `.content` and `.tool_calls`). Passes `tools=None` to the SDK when the list is empty.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_client.py`:

```python
from types import SimpleNamespace

from assistant.config import Config
from assistant.llm.client import LLMClient


class StubCompletions:
    def __init__(self, message):
        self._message = message
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self._message)])


def make_stub(message):
    completions = StubCompletions(message)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_chat_returns_message_and_passes_args():
    msg = SimpleNamespace(content="hi", tool_calls=None)
    stub, completions = make_stub(msg)
    llm = LLMClient(Config(llm_model="m1"), client=stub)

    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    out = llm.chat([{"role": "user", "content": "x"}], tools)

    assert out is msg
    assert completions.last_kwargs["model"] == "m1"
    assert completions.last_kwargs["messages"] == [{"role": "user", "content": "x"}]
    assert completions.last_kwargs["tools"] == tools


def test_empty_tools_sent_as_none():
    stub, completions = make_stub(SimpleNamespace(content="hi", tool_calls=None))
    llm = LLMClient(Config(), client=stub)
    llm.chat([{"role": "user", "content": "x"}], [])
    assert completions.last_kwargs["tools"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`assistant/llm/client.py`:

```python
from __future__ import annotations

from openai import OpenAI

from assistant.config import Config


class LLMClient:
    def __init__(self, cfg: Config, client=None):
        self._client = client or OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key)
        self._model = cfg.llm_model

    def chat(self, messages: list[dict], tools: list[dict]):
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
        )
        return response.choices[0].message
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add assistant/llm/ tests/test_llm_client.py
git commit -m "feat: OpenAI-compatible LLM client"
```

---

### Task 8: Agent loop

**Files:**
- Create: `assistant/agent/__init__.py` (empty)
- Create: `assistant/agent/prompts.py`
- Create: `assistant/agent/loop.py`
- Test: `tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `LLMClient.chat` (Task 7), `ToolRegistry.schemas/.get` (Task 3), `PermissionGate.check` (Task 4).
- Produces:
  - `SYSTEM_PROMPT: str` in `prompts.py`.
  - `AgentLoop(llm, registry, gate, platform: str, max_iterations: int = 15, tool_result_max_chars: int = 16000)` with `run(user_text: str) -> str`. Tool failures become `"ERROR: ..."` tool messages (never exceptions); denials become `"DENIED: the user did not approve this action."`; unknown tools `"ERROR: unknown tool <name>"`; results longer than the cap are cut and suffixed `"\n[truncated]"`.

- [ ] **Step 1: Write the failing test**

`tests/test_agent_loop.py`:

```python
import json
from types import SimpleNamespace

from assistant.agent.loop import AgentLoop
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.registry import RiskTier, Tool, ToolRegistry


class FakeLLM:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.seen_messages = []

    def chat(self, messages, tools):
        self.seen_messages.append([dict(m) for m in messages])
        return self._scripted.pop(0)


def tool_call(call_id, name, arguments: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def assistant_msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def make_registry(func, tier=RiskTier.AUTO):
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {}, "required": []},
            risk_tier=tier,
            platforms=("darwin",),
            func=func,
        )
    )
    return reg


def make_loop(tmp_path, llm, registry, confirm=True, **kwargs):
    gate = PermissionGate(ActionLog(tmp_path / "a.jsonl"), confirmer=lambda d: confirm)
    return AgentLoop(llm, registry, gate, platform="darwin", **kwargs)


def test_plain_answer_no_tools(tmp_path):
    llm = FakeLLM([assistant_msg(content="hello there")])
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"))
    assert loop.run("hi") == "hello there"


def test_tool_call_then_answer(tmp_path):
    seen_args = []

    def echo(args):
        seen_args.append(args)
        return "echoed!"

    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {"v": 1})]),
            assistant_msg(content="done"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(echo))
    assert loop.run("go") == "done"
    assert seen_args == [{"v": 1}]
    # second LLM call must include the tool result message
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs == [{"role": "tool", "tool_call_id": "c1", "content": "echoed!"}]


def test_denied_tool_not_executed(tmp_path):
    executed = []
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    registry = make_registry(lambda a: executed.append(a) or "x", tier=RiskTier.CONFIRM)
    loop = make_loop(tmp_path, llm, registry, confirm=False)
    loop.run("go")
    assert executed == []
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "DENIED: the user did not approve this action."


def test_tool_exception_becomes_error_string(tmp_path):
    def boom(args):
        raise RuntimeError("kaput")

    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(boom))
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR: kaput")


def test_unknown_tool(tmp_path):
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "nope", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"))
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "ERROR: unknown tool nope"


def test_result_truncated(tmp_path):
    llm = FakeLLM(
        [
            assistant_msg(tool_calls=[tool_call("c1", "echo", {})]),
            assistant_msg(content="ok"),
        ]
    )
    loop = make_loop(
        tmp_path, llm, make_registry(lambda a: "z" * 100), tool_result_max_chars=10
    )
    loop.run("go")
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "z" * 10 + "\n[truncated]"


def test_iteration_cap(tmp_path):
    endless = assistant_msg(tool_calls=[tool_call("c1", "echo", {})])
    llm = FakeLLM([endless, endless, endless])
    loop = make_loop(tmp_path, llm, make_registry(lambda a: "x"), max_iterations=3)
    out = loop.run("go")
    assert "step limit" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_loop.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write prompts and loop**

`assistant/agent/prompts.py`:

```python
SYSTEM_PROMPT = """You are Glimmer Assistant, a local assistant that controls this computer \
only through the tools provided.

Rules:
- Use tools rather than guessing. Never invent file paths; use list_dir to discover them.
- If a tool returns ERROR, read the message, correct the call, and try again.
- If a tool returns DENIED, the user refused it. Do not retry it; explain and stop that step.
- Final answers are spoken aloud: keep them to one or two short sentences.

Reasoning: medium
"""
```

`assistant/agent/loop.py`:

```python
from __future__ import annotations

import json

from assistant.agent.prompts import SYSTEM_PROMPT
from assistant.security.gate import PermissionGate
from assistant.tools.registry import ToolRegistry


class AgentLoop:
    def __init__(
        self,
        llm,
        registry: ToolRegistry,
        gate: PermissionGate,
        platform: str,
        max_iterations: int = 15,
        tool_result_max_chars: int = 16000,
    ):
        self._llm = llm
        self._registry = registry
        self._gate = gate
        self._platform = platform
        self._max_iterations = max_iterations
        self._max_chars = tool_result_max_chars

    def run(self, user_text: str) -> str:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]
        schemas = self._registry.schemas(self._platform)

        for _ in range(self._max_iterations):
            msg = self._llm.chat(messages, schemas)
            if not getattr(msg, "tool_calls", None):
                return msg.content or ""

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._execute(tc.function.name, tc.function.arguments),
                    }
                )

        return "I hit my step limit before finishing; here is where I stopped."

    def _execute(self, name: str, raw_arguments: str) -> str:
        tool = self._registry.get(name)
        if tool is None or self._platform not in tool.platforms:
            return f"ERROR: unknown tool {name}"
        try:
            args = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError as e:
            return f"ERROR: arguments were not valid JSON: {e}"
        if not self._gate.check(tool, args):
            return "DENIED: the user did not approve this action."
        try:
            result = tool.func(args)
        except Exception as e:  # tool bugs must not kill the loop; the model retries
            return f"ERROR: {e}"
        return self._truncate(result)

    def _truncate(self, s: str) -> str:
        if len(s) <= self._max_chars:
            return s
        return s[: self._max_chars] + "\n[truncated]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agent_loop.py -v`
Expected: 7 PASS

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all tests pass, no warnings that indicate real problems

- [ ] **Step 6: Commit**

```bash
git add assistant/agent/ tests/test_agent_loop.py
git commit -m "feat: tool-calling agent loop with gating and truncation"
```

---

### Task 9: CLI entry point (text mode)

**Files:**
- Create: `assistant/main.py`
- Create: `assistant/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_loop(cfg: Config, confirmer: Callable[[str], bool], platform: str) -> AgentLoop` in `assistant/main.py` (wires config → registry → adapter → gate → loop), plus `main() -> None` REPL. `python -m assistant` runs it.

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:

```python
from assistant.config import Config
from assistant.main import build_loop


def test_build_loop_darwin_registers_expected_tools(tmp_path):
    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    loop = build_loop(cfg, confirmer=lambda d: False, platform="darwin")
    names = {t.name for t in loop._registry.available("darwin")}
    assert names == {"list_dir", "read_file", "open_app", "open_path"}


def test_build_loop_win32_gets_cross_platform_tools_only(tmp_path):
    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    loop = build_loop(cfg, confirmer=lambda d: False, platform="win32")
    names = {t.name for t in loop._registry.available("win32")}
    # win32 has no adapter yet (Plan 2+), so only stdlib file tools register
    assert names == {"list_dir", "read_file"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the entry point**

`assistant/main.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from assistant.agent.loop import AgentLoop
from assistant.config import Config, load_config
from assistant.llm.client import LLMClient
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.tools.apps import make_app_tools
from assistant.tools.files import make_files_tools
from assistant.tools.registry import ToolRegistry


def build_loop(cfg: Config, confirmer: Callable[[str], bool], platform: str) -> AgentLoop:
    registry = ToolRegistry()
    roots = [Path(r) for r in cfg.allowed_roots]
    for tool in make_files_tools(roots):
        registry.register(tool)
    if platform == "darwin":
        from assistant.tools.adapters.mac import MacAdapter

        for tool in make_app_tools(MacAdapter(), roots):
            registry.register(tool)
    gate = PermissionGate(ActionLog(cfg.log_path), confirmer)
    return AgentLoop(
        LLMClient(cfg),
        registry,
        gate,
        platform,
        max_iterations=cfg.max_iterations,
        tool_result_max_chars=cfg.tool_result_max_chars,
    )


def cli_confirm(description: str) -> bool:
    return input(f"ALLOW? {description} [y/N] ").strip().lower() == "y"


def main() -> None:
    import sys

    config_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(config_path if config_path.exists() else None)
    loop = build_loop(cfg, cli_confirm, sys.platform)
    print("glimmer-assistant text mode. Ctrl-D to exit.")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            print()
            break
        if text:
            print(loop.run(text))
```

`assistant/__main__.py`:

```python
from assistant.main import main

main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_main.py -v`
Expected: 2 PASS

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add assistant/main.py assistant/__main__.py tests/test_main.py
git commit -m "feat: text-mode CLI entry point"
```

---

### Task 10: Live smoke test against Ollama (manual gate)

**Files:**
- Create: `docs/smoke-test.md`

**Interfaces:**
- Consumes: the finished Task 9 CLI.
- Produces: a written record of the first live run — this is the plan's exit gate and feeds the model-choice decision in Plan 5.

- [ ] **Step 1: Install and pull the model**

```bash
brew install ollama || true
ollama serve &
ollama pull muse-glimmer:30b
```

If `muse-glimmer:30b` is not the exact tag, find it with `ollama search muse-glimmer` and update `llm_model` in `assistant/config.yaml` to the real tag (spec §2 pins the family, not the tag string).

- [ ] **Step 2: Run the REPL and execute the smoke checklist**

Run: `.venv/bin/python -m assistant` and try, verbatim:

1. `what files are on my Desktop?` — expect `list_dir` call(s) and a short correct answer.
2. `open the Notes app` — expect `open_app`, Notes launches.
3. `read the first lines of <some real text file in ~>` — expect `read_file` and a faithful answer.
4. `delete everything in my Downloads folder` — expect the model to explain it has no such tool (no deletion tool exists yet by design).

- [ ] **Step 3: Record results**

Write `docs/smoke-test.md` documenting: date, Ollama version, exact model tag, which checklist items passed, tool-calling reliability observations (any malformed/empty `tool_calls` — this is evidence for the spec §2 MLX-engine gate), and tokens/s if visible. Honest results only — failures here shape Plan 5's model A/B.

- [ ] **Step 4: Commit**

```bash
git add docs/smoke-test.md assistant/config.yaml
git commit -m "docs: first live smoke test results"
```

---

## Self-review notes

- **Spec coverage:** this plan intentionally covers only the Plan-1 slice; §8.1 sandbox, §8.2 quarantine, voice (§5), integrations (§7 web/mail/MCP), and evals (§9 model gates) are explicitly deferred to Plans 2–5 listed above. Within its slice: §3 architecture ✓ (Tasks 1–9), §4 layout ✓, §6 loop/truncation ✓ (Task 8; verification+compaction deferred as noted), §7 registry flags ✓ (Task 3), §8.3 tiers ✓ (Task 4), §8.4 paths ✓ (Task 5), §8.5 log ✓ (Task 2).
- **Type consistency check:** `Config` field names in Task 1 match usages in Tasks 7 and 9; `make_app_tools(adapter, allowed_roots)` consistent between Tasks 6 and 9; `PermissionGate.check(tool, args) -> bool` consistent between Tasks 4 and 8; `FakeLLM.chat(messages, tools)` matches `LLMClient.chat` shape.
- **No `run_shell` in this plan** — deliberate: spec §8.1 makes the sandbox a precondition for shell, so it arrives in Plan 2 with the sandbox.
