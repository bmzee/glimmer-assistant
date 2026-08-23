from __future__ import annotations

from pathlib import Path
from typing import Callable

from assistant.agent.loop import AgentLoop
from assistant.config import Config, load_config
from assistant.llm.client import LLMClient
from assistant.security.confirm import ConfirmRequest
from assistant.security.gate import PermissionGate
from assistant.security.log import ActionLog
from assistant.security.trust import SessionTrust
from assistant.tools.apps import make_app_tools
from assistant.tools.files import make_files_tools
from assistant.tools.registry import ToolRegistry


def build_loop(cfg: Config, confirmer: Callable[[ConfirmRequest], bool], platform: str) -> AgentLoop:
    registry = ToolRegistry()
    roots = [Path(r) for r in cfg.allowed_roots]
    for tool in make_files_tools(roots):
        registry.register(tool)
    if platform == "darwin":
        from assistant.tools.adapters.mac import MacAdapter
        from assistant.tools.shell import make_shell_tool
        from assistant.tools.system import make_system_tools

        adapter = MacAdapter()
        for tool in make_app_tools(adapter, roots):
            registry.register(tool)
        # The configured audit-log path joins the screenshot denylist so tool
        # writes can never destroy the action record (Rule-of-Two's evidence).
        for tool in make_system_tools(
            adapter, roots, protected_paths=[Path(cfg.log_path)]
        ):
            registry.register(tool)
        registry.register(make_shell_tool(roots))

    trust = SessionTrust()
    log = ActionLog(cfg.log_path)
    gate = PermissionGate(log, confirmer, trust=trust)

    if cfg.enable_web:
        try:
            from assistant.tools.web import make_web_tools

            for tool in make_web_tools():
                registry.register(tool)
        except Exception as e:
            print(f"[web tools unavailable: {e}]")

    if cfg.enable_apple and platform == "darwin":
        try:
            from assistant.tools.apple import make_apple_tools

            for tool in make_apple_tools():
                registry.register(tool)
        except Exception as e:
            print(f"[apple tools unavailable: {e}]")

    if cfg.enable_m365 and cfg.m365_client_id:
        try:
            from assistant.tools.msgraph import GraphAuth, GraphClient, make_msgraph_tools

            client = GraphClient(GraphAuth(cfg.m365_client_id))
            for tool in make_msgraph_tools(client):
                registry.register(tool)
        except Exception as e:
            print(f"[m365 tools unavailable: {e}]")

    if cfg.mcp_servers:
        try:
            from assistant.tools.mcp_client import make_mcp_tools

            mcp_tools = make_mcp_tools(cfg.mcp_servers)
            for tool in mcp_tools:
                registry.register(tool)
            if not mcp_tools:
                n = len(cfg.mcp_servers)
                print(
                    f"[mcp: 0 tools registered from {n} configured server(s) "
                    "— no session factory configured]"
                )
        except Exception as e:
            print(f"[mcp tools unavailable: {e}]")

    return AgentLoop(
        LLMClient(cfg),
        registry,
        gate,
        platform,
        max_iterations=cfg.max_iterations,
        tool_result_max_chars=cfg.tool_result_max_chars,
        log=log,
        trust=trust,
        context_max_tokens=cfg.context_max_tokens,
        compact_threshold=cfg.compact_threshold,
    )


def cli_confirm(request) -> bool:
    return input(f"ALLOW? {request.preview} [y/N] ").strip().lower() == "y"


def _make_voice_event_handler(notifier=None):
    """Log every turn AND surface it visibly.

    The log is a record, not an interface -- nobody watches a file. Packaged,
    audio is the only output channel, so a missed reply is simply gone unless
    it also lands in Notification Centre.
    """
    from assistant.voice.notify import Notifier

    notifier = notifier if notifier is not None else Notifier()

    def handle(name, payload):
        if name == "transcribed":
            print(f"you said: {payload}")
        elif name == "answered":
            print(f"assistant: {payload}")
        elif name == "error":
            print(f"[error] {payload}")
        notifier.notify(name, payload)

    return handle


def build_voice_session(cfg, platform, *, stt=None, tts=None, ptt=None):
    from assistant.voice.session import VoiceSession

    if stt is None:
        from assistant.voice.stt import ParakeetSTT

        stt = ParakeetSTT(cfg.voice_stt_model)
    if tts is None:
        from assistant.voice.tts import KokoroTTS, SafeTTS

        # Wrap in SafeTTS: in an app whose only output is audio, a dead
        # synthesiser means the user asks and hears nothing at all.
        tts = SafeTTS(KokoroTTS(cfg.voice_tts_voice))
    if ptt is None:
        from assistant.voice.audio import DoubleTapToggle, HotkeyPushToTalk
        from assistant.voice.click import ClickToTalk

        if cfg.voice_activation == "listen":
            from assistant.voice.vad import VoiceActivityCapture

            ptt = VoiceActivityCapture(
                min_seconds=cfg.voice_min_utterance_seconds,
                speech_level=cfg.voice_speech_level,
                silence_seconds=cfg.voice_silence_seconds,
            )
        elif cfg.voice_activation == "click":
            # No global hotkey, so no Input Monitoring required.
            ptt = ClickToTalk(
                min_seconds=cfg.voice_min_utterance_seconds,
                max_seconds=cfg.voice_max_session_seconds,
            )
        elif cfg.voice_activation == "hold":
            ptt = HotkeyPushToTalk(
                cfg.voice_hotkey, min_seconds=cfg.voice_min_utterance_seconds
            )
        else:
            ptt = DoubleTapToggle(
                cfg.voice_hotkey,
                min_seconds=cfg.voice_min_utterance_seconds,
                tap_window=cfg.voice_tap_window_seconds,
                max_seconds=cfg.voice_max_session_seconds,
            )

    from assistant.voice.confirm import SpokenConfirmer

    confirmer = SpokenConfirmer(ptt, stt, tts)
    loop = build_loop(cfg, confirmer, platform)
    return VoiceSession(
        ptt,
        stt,
        loop,
        tts,
        min_utterance_seconds=cfg.voice_min_utterance_seconds,
        on_event=_make_voice_event_handler(),
    )


def main() -> None:
    import sys

    from assistant.config import resolve_config_path

    cfg = load_config(resolve_config_path())

    if "--voice" in sys.argv:
        print("loading voice models...")
        session = build_voice_session(cfg, sys.platform)
        print("glimmer-assistant voice mode. Hold the hotkey to talk. Ctrl-C to exit.")
        session.run_forever()
        return

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
