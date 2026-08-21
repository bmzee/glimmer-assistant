# Glimmer Assistant — Design Specification

**Status:** Approved 2026-08-21 (design reviewed against Aug-2026 state of the art by five parallel research audits; amendments folded in).
**Owner:** bmz
**Targets:** macOS (Apple Silicon, M3 Max 128GB) first; Windows second. Python v1; optional Rust host rewrite later for single-binary packaging.

## 1. Goal

A fully local, voice-activated PC assistant. The user holds a push-to-talk hotkey, speaks a request ("archive the invoices folder and email Sarah the summary"), and the assistant plans and executes it using structured OS/app/API tools, speaking the result back. No cloud LLM; all inference on-device.

### v1 capabilities
- Apps, files & system: open/close/focus apps, find/move/organize files, volume/settings basics, screenshots.
- Web tasks: open sites, search, read/summarize pages, fill simple form fields (gated).
- Email & calendar: Apple Mail/Calendar (Mac, local) and Microsoft 365 via Graph (cross-platform). Read/summarize/draft/check schedule freely; send/create gated.

### Non-goals for v1
- Screenshot-based GUI control (v2; see §10).
- Wake word / always-listening (v2; openWakeWord).
- Long-term memory across sessions.
- Multi-agent orchestration.

## 2. Model & serving

- **Model:** Meta **Muse-Glimmer-30B** (Apache 2.0), K-Quant-Dynamic quantization, DFlash speculative-decoding drafter enabled. Chosen for best-in-class local tool calling (MCP Atlas 75.5); its known weakness (OSWorld 65.9) is the GUI path we deliberately avoid in v1.
- **Server:** **Ollama** on both platforms, OpenAI-compatible endpoint (`http://localhost:11434/v1`). Base URL, model name, and engine are config values — swapping to LM Studio/vLLM or another model is a config change, not code.
- **Reasoning effort:** `medium` default; the system prompt permits the model to request `high` for multi-step tasks.
- **Contender clause:** **Qwen3.8-27B** (released 2026-08-14) reportedly beats Glimmer broadly, incl. OSWorld 84.3. Before v1 ships, run the scripted 10-task eval (§9) against both through the same endpoint; keep the winner. All prompts/tools must remain model-agnostic.

### Known risks to verify empirically (acceptance gates)
1. **Ollama MLX engine structured-output bug** ([ollama#17013](https://github.com/ollama/ollama/issues/17013)): MLX engine silently ignores JSON-schema `format` constraints; related empty-`tool_calls` report (#8095). Gate: structured-output + multi-arg tool-call test suite must pass on the MLX engine; if it fails, pin the GGUF engine (accept lower tok/s) until fixed.
2. **Freshness:** Glimmer llama.cpp support (≥ b10362) and DFlash integration are days old. Pin Ollama/llama.cpp versions in config; verify system-prompt/chat-template delivery on the actual pulled model.
3. **DFlash on Windows** (llama.cpp/CUDA path) is unconfirmed — verify at port time; it is an optimization, not a dependency.

## 3. Architecture

```
[PTT hotkey (pynput)]
   └─ [Audio capture (sounddevice) + Silero VAD]
        └─ [Streaming STT: Parakeet-TDT (MLX on Mac / ONNX on Win)]
             └─ [Agent loop] ⇄ [Ollama: Muse-Glimmer-30B + DFlash]
                   ├─ [Tool registry: in-process tools + embedded MCP client]
                   │      ├─ platform-neutral tools → [PlatformAdapter: mac.py / windows.py]
                   │      ├─ pinned/audited MCP servers (filesystem, macos-automator, ms-365, Windows-MCP)
                   │      └─ [Sandbox: sandbox-exec (Mac) / AppContainer (Win)]
                   ├─ [Permission gate (risk-tiered) + JSONL action log]
                   ├─ [Quarantine parser for untrusted content (web/email)]
                   └─ [Post-action verification step]
             └─ [TTS: Kokoro-82M (Piper/`say` fallback)] + notifications
```

One Python daemon; Ollama as a sidecar. Everything OS-specific lives in `PlatformAdapter` + platform-flagged tools; ~85% of code is shared with Windows.

## 4. Repo layout

```
glimmer-assistant/
  assistant/
    main.py                 # daemon entry: hotkey listener + event loop
    voice/                  # capture.py, vad.py, stt.py, tts.py
    agent/                  # loop.py, prompts.py, verify.py, compaction.py
    llm/client.py           # OpenAI-compatible client (base URL from config)
    tools/
      registry.py           # Tool base, schemas, platform + risk-tier flags
      files.py apps.py system.py web.py
      mail_apple.py calendar_apple.py    # darwin-only flags
      msgraph.py                         # cross-platform
      mcp_client.py                      # embedded MCP client for pinned servers
      adapters/base.py mac.py windows.py # windows.py stubbed in v1
    security/
      sandbox.py            # sandbox-exec profile wrapper (win: appcontainer later)
      quarantine.py         # untrusted-content parsing + datamarking
      gate.py log.py paths.py           # tiered confirmations, JSONL log, path canonicalization
    config.yaml
  tests/
  evals/tasks.yaml          # scripted 10-task model eval
  docs/spec.md docs/plan.md
```

## 5. Voice pipeline (SOTA-audited choices)

- **Activation:** push-to-talk global hotkey (pynput; macOS Accessibility permission granted by user once). Deliberate v1 choice over wake word — privacy + no false triggers.
- **Capture:** sounddevice (PortAudio) + **Silero VAD** (30ms frames) to trim silence.
- **STT:** **NVIDIA Parakeet-TDT** — `parakeet-mlx` on Mac (GPU/ANE), `onnx-asr`/sherpa-onnx on Windows (CUDA/DirectML). Streaming: transcribe *during* the PTT hold so the transcript is ~complete at key-release (~220ms p50). Rationale: faster-whisper is CPU-only on Apple Silicon (no Metal, longstanding open issue) and distil-small is beaten on WER and latency.
- **TTS:** **Kokoro-82M** (Apache 2.0) — near-Piper latency (~90ms first audio), markedly more natural, runs on CPU so the GPU stays free for the LLM. Fallbacks: Piper (note: maintained fork is GPL-3.0), macOS `say`. Final LLM answer streams to TTS sentence-by-sentence.
- **v2:** openWakeWord for always-listening (free, cross-platform); Porcupine rejected (commercial licence), microWakeWord (MCU-only).

## 6. Agent loop

- Plain tool-calling loop, max 15 iterations: transcript → messages + tool schemas → model → execute calls → append results → repeat until final text.
- **Post-action verification** (per UI-TARS-2 / Agent-S3 practice): after each mutating tool call, run a cheap check that the expected state change occurred (structured tool-result check or state re-query) and feed a mismatch back to the model as a correction prompt. Glimmer is trained for diagnose-and-retry; errors return as structured strings, never exceptions.
- **Context management:** compaction (anchored iterative summarization) triggers at **~65% of the 131K window**; every individual tool result hard-capped at **2–4K tokens** at the tool layer (truncation happens before compaction ever needs to).
- Session-only memory. No framework — validated for this deployment shape (single-user, local, Ollama); revisit only if requirements grow to multi-agent.

## 7. Tools & integrations

- **Tool registry:** each tool declares `platforms` (registry hides unavailable tools from the model) and `risk_tier` (§8).
- **Reuse over rebuild — pinned MCP servers** via embedded MCP client, each version-pinned, audited before adoption (2026 scans: most community MCP servers have path-traversal/auth flaws), and routed through our permission gate + sandbox like any in-process tool:
  - `@modelcontextprotocol/server-filesystem` (official) — file ops beyond stdlib basics
  - `steipete/macos-automator-mcp` (MIT) — AppleScript/JXA recipes
  - `softeria/ms-365-mcp-server` — Microsoft Graph mail/calendar
  - `CursorTouch/Windows-MCP` or `sbroenne/mcp-windows` — Windows UIA (v2)
- **PlatformAdapter** interface: `launch_app, quit_app, list_windows, focus_window, set_volume, screenshot, open_path, run_shell`.
  - **MacAdapter:** AppleScript/osascript primary (Mail, Calendar, Finder, System Events) **plus AXUIElement accessibility-tree reader** (MacPaw `macapptree`, MIT) for generic UI state and apps without scripting dictionaries; App Intents / `shortcuts run` as tertiary path. Handle macOS Tahoe's per-app Apple Events/TCC consent prompts gracefully (first-use prompts expected, not errors).
  - **WindowsAdapter (v2):** PowerShell + pywinauto/UI Automation (matches Microsoft's Windows Agent Arena methodology). At port time, evaluate Windows' native MCP/agentic surface (in Insider preview) as a substitute for hand-rolled UIA.
- **Web:** Playwright, persistent profile. `read_page` returns **accessibility-tree snapshots** (Playwright-MCP style), never raw DOM — better for the model, cheaper in tokens. `open_url`, `search_web`, `fill_form_field` (gated). Raw-CDP optimization deferred.
- **Email/calendar:** Apple Mail/Calendar via AppleScript (darwin-only, `_local` suffix). Microsoft 365 via Graph + `msal` **device-code flow** (confirmed undeprecated) — the user completes OAuth themselves in a browser; the assistant never sees credentials. Auth initiation shows a distinct, unambiguous UI (device-code phishing rose ~15x in 2026 — the user must recognize a legitimate, self-initiated prompt). Windows-only WAM broker auth is a v2 nicety.

## 8. Security model (2026-baseline)

Layered: sandbox is the boundary; confirmations are the second layer; the model is never the enforcement point.

1. **OS sandbox (launch blocker, not v2).** All `run_shell` and file-mutation execution wrapped in `sandbox-exec` (Seatbelt) on macOS: writes restricted to session-scoped + user-approved directories, network egress denied except an explicit allowlist. Windows: AppContainer/Windows Sandbox at port time. Actions needing to cross the sandbox boundary require confirmation.
2. **Untrusted-content quarantine (Rule of Two).** Web pages and emails are untrusted input. They are parsed in a quarantined pass that returns structured, **datamarked** content to the planning context (spotlighting), never raw free text. Once a session/task has ingested untrusted content, outbound-action tools (send email, submit form, shell with network) are **elevated**: blocking confirmation with full preview, regardless of tier. This breaks the lethal trifecta (private access + untrusted input + external comms) that produced the 2025–26 incident class (GitHub MCP exfiltration, Comet hijacks, Supabase/Cursor).
3. **Risk-tiered confirmations** (flat confirm-everything is a documented fatigue attack vector):
   - **Tier 0 auto:** read-only (list/read/search/screenshot/calendar read).
   - **Tier 1 async-undo:** low-blast-radius mutations (move file, create draft, create event) — notification with an undo window; deletes go to Trash, never `rm`.
   - **Tier 2 blocking preview:** send email (full draft shown), submit form, shell commands, anything crossing sandbox/network boundaries — explicit spoken/clicked yes per action.
   - **Tier 3 never:** passwords/payment entry, purchases, emptying trash, system/security settings. Hard-coded refusals.
4. **Path & provenance hygiene:** canonicalize + allowlist every filesystem/shell path constructed from model output (the GitHub-MCP CVE class). Pin MCP tool definitions at approval time; refuse silently-changed definitions.
5. **Audit:** JSONL action log of every tool execution (args, tier, confirmation outcome, result hash).

## 9. Testing & acceptance

- TDD throughout (tests before implementation, per task).
- **Unit:** every tool against a `FakeAdapter` (no side effects); schema round-trip tests (OpenAI tool format); gate tests (tier enforcement, quarantine-elevation, path canonicalization); sandbox profile tests (write-outside-scope and network egress must fail).
- **Integration:** scripted end-to-end with canned model responses; MCP client against pinned server versions.
- **Model gates:** (a) structured-output + multi-arg tool-calling suite passes on Ollama MLX engine, else pin GGUF; (b) `evals/tasks.yaml` — 10 scripted spoken-task evals runnable against any OpenAI-compatible endpoint; run vs Glimmer and Qwen3.8-27B, ship the winner.
- **Voice:** latency budget test — PTT release → first TTS audio ≤ 2.5s p50 for a no-tool answer.

## 10. v2 roadmap

- **GUI fallback:** accessibility tree + screenshot fed to a **dedicated grounding model** (UI-TARS-1.5/2 or Holo2-class) that resolves click coordinates; Glimmer plans/verifies only (its 1.8B vision encoder is too weak for pixel grounding).
- Wake word (openWakeWord); WindowsAdapter + AppContainer sandbox + WAM auth; Rust host rewrite for single-binary distribution; raw-CDP browser driver if latency demands.

## 11. Decision log

| Decision | Choice | Rejected | Why |
|---|---|---|---|
| Language (v1) | Python | Rust, native apps | Iteration speed dominates accuracy tuning; runtime is native engines anyway; Rust = later packaging step |
| Framework | None (hand-rolled loop) | LangGraph, PydanticAI, vendor SDKs | Wrong deployment shape; SDKs don't support local Ollama; SOTA agents use flat loops |
| STT | Parakeet-TDT (MLX/ONNX) | faster-whisper distil-small | faster-whisper is CPU-only on Apple Silicon; Parakeet wins WER + latency |
| TTS | Kokoro-82M | Piper (default), Chatterbox | Piper fork is GPL-3.0 + robotic; Chatterbox needs the GPU the LLM is using |
| Server | Ollama (engine-pinned) | vLLM-metal, LM Studio | Cross-platform parity, MLX under the hood, config-swappable anyway |
| Model | Muse-Glimmer-30B, eval-gated vs Qwen3.8-27B | larger MoE (gpt-oss-120B etc.) | Glimmer leads tool calling; big MoEs don't beat good 27–30Bs here; eval decides |
| Control substrate (Mac) | AppleScript + AXUIElement + App Intents | AppleScript alone; pure vision | Coverage for dictionary-less apps; vision grounding immature |
| Browser | Playwright (a11y-tree snapshots) | browser-use/raw CDP, vision agents | SOTA pattern; CDP is a v2 speed optimization |
| Security | Sandbox + quarantine + tiered gates | Confirmation-only | 2026 baseline; confirmation-only is below every shipped peer |
