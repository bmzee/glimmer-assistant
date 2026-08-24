# Spec coverage audit

**Date:** 2026-08-22 · **Against:** `docs/spec.md` · **Branch:** `worktree-evals-quality`

Every normative clause in the spec, checked against the code. The point of this
document is the ✗ and ⚠️ rows: what the spec asks for and we have **not** built.

Legend: ✅ built · ⚠️ built differently than specified (with rationale) ·
✗ not built · ⏭️ explicitly deferred to v2 by the spec itself

---

## §2 Model & serving

| Clause | Status | Evidence |
|---|---|---|
| Muse-Glimmer-30B via Ollama | ⚠️ | Default is `nemotron-3.5-lightning:30b-a3b-q4_K_M`. The spec's **contender clause** required an A/B before shipping; the original A/B raced only two of the three installed models. In the three-way re-run all three score 10/10, so speed decides: Nemotron is a mixture-of-experts (~3B active/token) and decodes at 86.8 tok/s against Glimmer's 29.3 and Qwen's 14.8. Licence is NVIDIA Open Model, not Apache 2.0. `docs/model-ab.md`. |
| K-Quant-Dynamic quantization | ✅ | q4-class GGUF, ~18 GB. |
| **DFlash speculative-decoding drafter** | ✗ | Never enabled. Plain GGUF build. `muse-glimmer:30b-mlx-bf16-dflash` untested — and bf16@30B is ~60 GB vs 18 GB q4, so on bandwidth-bound hardware DFlash's ~1.7× may not cover 3.3× more bytes/token. |
| Gate: structured output on MLX engine, else pin GGUF | ✅ | Bug does not reproduce; both models returned schema-valid JSON. No pin needed. `docs/model-ab.md`. |
| Pin Ollama/llama.cpp versions in config | ✗ | Not implemented. Config carries no version pin. |

## §5 Voice pipeline

| Clause | Status | Evidence |
|---|---|---|
| Parakeet-TDT STT (MLX on Mac) | ✅ | `assistant/voice/stt.py`, 0.13s median. |
| Kokoro-82M TTS | ✅ | `assistant/voice/tts.py`, ~0.3s to first audio after the phonemizer fix. |
| Streaming STT *during* PTT hold | ✗ | Transcription runs **after** key release, not during. At 0.13s it is not on the critical path, so this is a latency optimization we did not need. |
| Final answer streams to TTS sentence-by-sentence | ✅ | Built this session. `assistant/voice/streaming.py`, `AgentLoop.run(on_sentence=)`. |
| Fallbacks: Piper, macOS `say` | ✗ | Not implemented. A Kokoro failure ends the turn (the session survives it). |

## §6 Agent loop

| Clause | Status | Evidence |
|---|---|---|
| Plain tool-calling loop, max 15 iterations | ✅ | `assistant/agent/loop.py`. |
| **Post-action verification** after each mutating call | ⚠️ | Implemented as a *corrective hint* appended to failed Tier≥1 results ("this may have partially completed; verify with a read-only tool"), **not** a state re-query. Ruling R1: a full diff costs a model round-trip per action; the cheap 90% is stopping blind retries. Revisit if evals show retry loops. |
| Compaction at ~65% of 131K | ✅ | `assistant/agent/compaction.py`; anchored, offline, tool-message-safe. |
| Tool results capped 2–4K tokens at the tool layer | ✅ | `tool_result_max_chars: 16000` ≈ 4K tokens, applied before compaction. |
| Session-only memory, no framework | ✅ | No persistence between sessions. |

## §7 Tools & integrations

| Clause | Status | Evidence |
|---|---|---|
| Registry declares `platforms` + `risk_tier` | ✅ | `assistant/tools/registry.py`; invariants table-tested. |
| **PlatformAdapter: 8 methods** | ✅ | All built. `run_shell` deliberately stays in `tools/shell.py` — it must be sandbox-wrapped (§8.1), and routing a security boundary through a plain adapter method would weaken it. Documented on the ABC. |
| MacAdapter: AppleScript primary | ✅ | `assistant/tools/apple.py` (Mail, Calendar), `adapters/mac.py`. |
| MacAdapter: **AXUIElement accessibility reader** (`macapptree`) | ✗ | Not built. No generic UI-state reading. |
| MacAdapter: App Intents / `shortcuts run` tertiary | ✗ | Not built. |
| Handle TCC prompts gracefully | ✅ | `-1743` mapped to a remediation hint naming Automation settings. |
| Web: Playwright, persistent profile, aria snapshots | ✅ | `assistant/tools/web.py`, `aria_snapshot()`. |
| Web: `fill_form_field` (gated) | ✅ | CONFIRM tier **and** `outbound=True` — it puts data into a remote page, so Rule-of-Two elevation must apply. Does not echo the filled value back into context. |
| Email/calendar: Apple + M365 device-code | ✅ | `apple.py`, `msgraph.py`. |
| **Pinned MCP servers** (4 named) | ✗ | Client exists (`mcp_client.py`) but **no server is adopted or configured**; the launcher is scaffolded and inert. None of the four named servers is in use. |
| WindowsAdapter | ⏭️ | v2 per spec. |

## §8 Security model

| Clause | Status | Evidence |
|---|---|---|
| 1. `sandbox-exec` wrapping shell/file mutation | ✅ | `security/sandbox.py`, deny-default, no network allow. SBPL injection fixed. |
| 2. Untrusted-content quarantine, datamarked | ✅ | `security/quarantine.py`, unguessable per-call nonce. |
| 2. Outbound elevation after untrusted ingest | ✅ | `security/trust.py` + `gate.py`; enforced in the gate, not the prompt. |
| 3. Risk tiers 0–3 | ✅ | `RiskTier`; NEVER refused before elevation is computed. |
| 3. Tier 1 **async-undo window**; deletes to Trash | ✗ | Tiers exist and no tool calls `rm`, but there is **no undo mechanism and no notification**, so `gate.py:33` auto-approves Tier 1. **This is LIVE, not latent:** `open_app`, `focus_window`, `set_volume`, `open_url` are UNDO and execute unconfirmed. An earlier revision of this document claimed no tool was Tier 1 — that was wrong. |
| 4. Canonicalize + allowlist model-derived paths | ✅ | `security/paths.py`, `resolve_safe`. |
| 4. **Pin MCP tool definitions; refuse silent changes** | ✗ | Not implemented. |
| 5. JSONL audit log with result hash | ✅ | `security/log.py`; eval ground truth reads from it. |

## §9 Testing & acceptance

| Clause | Status | Evidence |
|---|---|---|
| TDD throughout | ✅ | 514 tests; guard tests proven to fail on their specific bug. |
| Unit: tools, schema round-trip, gate, sandbox profile | ✅ | Including write-outside-scope and network-egress denial. |
| Integration: canned responses; MCP against pinned versions | ⚠️ | Canned-response integration ✅. MCP-against-pinned-server ✗ (no server adopted). |
| Model gate (a): structured output | ✅ | Passes; no GGUF pin needed. |
| Model gate (b): 10 evals vs both models | ✅ | 10/10 both. `docs/model-ab.md`. |
| **Voice: ≤2.5s p50 to first TTS audio** | ⚠️ | **Passes on the easy case, misses on a real one.** "say hello in one short sentence": **1.74s p50** ✅. "what can you help me with?" with the full 20-tool schema: **5.23s p50** ❌. Both are reported because quoting only the first is how this document previously described a ~10x miss as 0.09s. Improved ~4x by switching to a mixture-of-experts model; see `docs/model-ab.md`. |

---

## Summary of real gaps

**Closed in this pass:**
- **Voice input never worked from the packaged app at all.** STT wrote a temp
  WAV and let `parakeet_mlx` decode it by spawning `ffmpeg`, which is not on the
  PATH a GUI-launched process inherits. Every turn raised, and the user heard
  "Sorry, something went wrong." Now transcribes from the in-memory array. This
  was invisible to the test suite: the STT tests mocked `transcribe` and
  asserted the `.wav` path, pinning the bug in place.
- **`build_app.py` produced a bundle with no UI**: it launched the terminal
  entry point, skipping preflight, the capability report, the window and the
  crash dialog, with `LSUIElement: True` hiding the Dock icon and suppressing
  the microphone prompt. `build_dist.py` was already correct.
- PlatformAdapter completed (quit/list-windows/focus/volume/screenshot). Two
  bugs found only by live testing — both AppleScript, both invisible to the
  twelve passing unit tests. See the commit for the -1700/-1719 detail.
- `fill_form_field` built, gated CONFIRM + outbound.

**Security clauses still not met:**
1. **MCP definition pinning** (§8.4) — unmet, though latent: no MCP server is
   adopted, so nothing is currently unpinned in practice.
2. **Tier 1 undo window** (§8.3) — **unmet and live.** Four tools (`open_app`,
   `focus_window`, `set_volume`, `open_url`) are UNDO and therefore run with no
   confirmation and no undo. A red-team audit found this; a previous revision of
   this document asserted no tool was Tier 1, which was false. `quit_app` and
   `open_path` were promoted to CONFIRM rather than relying on the missing
   mechanism. See `docs/security-audit.md`.

**Acceptance gate not met:**
3. **Voice latency: 1.74s p50 on the easy case (passes), 5.23s on a real
   question (misses).** Two earlier revisions of this document got this wrong in
   opposite directions: first reporting 2.59s as a 0.09s miss, then 14.5–23.9s
   measured cold. The actual cause was never reasoning tokens alone — it was the
   model. `docs/model-ab.md` had raced two of the three installed models; the
   unraced one is a mixture-of-experts (~3B active vs dense 27B) and decodes 5.9x
   faster at the same 10/10. (`docs/latency.md`)

**Deliberately not built** (documented, with rationale): DFlash, streaming STT during hold, TTS fallbacks, AXUIElement reader, App Intents, MCP server adoption, Windows adapter.

Items 1–3 are recorded as known and open, not silently carried.
