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
| Muse-Glimmer-30B via Ollama | ⚠️ | Default is `qwen3.8:27b`. The spec's own **contender clause** required an A/B before shipping; both scored 10/10 and Qwen won on tool discipline. `docs/model-ab.md`. |
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
| TDD throughout | ✅ | 481 tests; guard tests proven to fail on their specific bug. |
| Unit: tools, schema round-trip, gate, sandbox profile | ✅ | Including write-outside-scope and network-egress denial. |
| Integration: canned responses; MCP against pinned versions | ⚠️ | Canned-response integration ✅. MCP-against-pinned-server ✗ (no server adopted). |
| Model gate (a): structured output | ✅ | Passes; no GGUF pin needed. |
| Model gate (b): 10 evals vs both models | ✅ | 10/10 both. `docs/model-ab.md`. |
| **Voice: ≤2.5s p50 to first TTS audio** | ✗ | **Missed by ~10x, not by 0.09s.** Real turns are **14.5s** (one tool) to **23.9s** (no tool) to the first spoken word. The 2.59s previously reported here was measured with tool groups disabled on *"say hello"* — the easiest case the app supports, not a description of use. `docs/latency.md`. |

---

## Summary of real gaps

**Closed in this pass:**
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
3. **Voice latency: 14.5–23.9s to first spoken word, against a 2.5s gate.** An
   earlier revision of this document reported 2.59s and called it a 0.09s miss;
   that figure came from a benchmark with tool groups disabled and does not
   describe a real turn. ~60% of generated tokens are reasoning the user never
   hears, and this model emits all of it before any content, so streaming cannot
   help. Suppressing reasoning was measured and rejected (10/10→9/10, `</think>`
   leaking into speech). Mitigated — not fixed — by speaking an acknowledgement
   the moment the transcript lands. Closing this gate needs a different model.
   (`docs/latency.md`)

**Deliberately not built** (documented, with rationale): DFlash, streaming STT during hold, TTS fallbacks, AXUIElement reader, App Intents, MCP server adoption, Windows adapter.

Items 1–3 are recorded as known and open, not silently carried.
