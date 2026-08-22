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


def cli_confirm(request) -> bool:
    return input(f"ALLOW? {request.preview} [y/N] ").strip().lower() == "y"


def main() -> None:
    import sys

    config_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(config_path if config_path.exists() else None)
    loop = build_loop(cfg, cli_confirm, sys.platform)
    print("glimmer-assistant text mode. Ctrl-D to exit.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text:
            try:
                print(loop.run(text))
            except KeyboardInterrupt:
                print("\n(interrupted)")
            except Exception as e:
                print(f"error: {e}")
