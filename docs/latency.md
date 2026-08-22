# Voice latency: spec §9 gate

**Date:** 2026-08-22
**Host:** MacBook Pro, Apple M3 Max, 128 GB, macOS 26.6.2 — **AC power, `powermode 0`**, load ~4–6
**Model under test:** `qwen3.8:27b` (current default)
**Gate:** `docs/spec.md` §9 — *PTT release → first TTS audio ≤ 2.5s p50 for a no-tool answer.*

## Result

| Stage | Median | Share |
|---|---:|---:|
| STT (Parakeet-TDT, MLX) | 0.12s | 3% |
| **Agent loop (LLM)** | **2.95s** | **82%** |
| TTS first audio (Kokoro-82M) | 0.51s | 14% |
| **Total** | **3.58s** | |
| **Gate** | **≤ 2.50s** | |
| **Verdict** | ❌ **MISS by 1.08s** | |

## How we got here

The first measurement of this gate read **10.87s**. Two defects were found and
removed, neither of which was a property of the models:

| | STT | Agent | TTS | Total | vs gate |
|---|---:|---:|---:|---:|---:|
| Initial measurement | 0.16s | 8.38s | 2.33s | **10.87s** | miss by 8.37s |
| …on AC power (`powermode 0`) | 0.11s | 2.85s | 2.12s | **5.08s** | miss by 2.58s |
| …with the TTS phonemizer fix | 0.12s | 2.95s | 0.51s | **3.58s** | miss by 1.08s |

### Defect 1 — the host was throttled (−5.79s)

Every earlier number was recorded on **battery with macOS Low Power Mode
active** (`pmset -g custom` → `Battery Power: powermode 1`) under load average
~21. On AC with `powermode 0` the agent step alone fell from 8.38s to 2.85s.
This was a measurement error, not a system defect. See `docs/model-ab.md`.

### Defect 2 — a 1.8s fixed cost in TTS (−1.61s)

This one was real. `KokoroTTS.speak()` cost ~2.0s per utterance, against the
~90ms `docs/spec.md` §5 cites for Kokoro. Profiling isolated it:

- Synthesis time was **~1.9s fixed + ~0.14s per second of audio**. A 6-character
  sentence cost as much as an 84-character one.
- A long-lived `KokoroTTS` instance paid it exactly as much as a fresh one, so
  it was not object-construction overhead.
- Splitting `Kokoro.create()` showed **`phonemize()` alone was 1.80s of the
  2.05s** — and it measured a flat 1.79s for 3, 32, and 97 characters of input.

The cause is in `kokoro_onnx.tokenizer`, which does grapheme-to-phoneme
conversion through the module-level `phonemizer.phonemize()` convenience
function. That constructs a **new espeak backend on every call**. Measured
directly: building an `EspeakBackend` costs 2.319s, after which `phonemize()`
returns in **0.0001s**.

**Fix** (`assistant/voice/tts.py`): build one process-wide `EspeakBackend`,
cached per language, and pass the resulting phonemes to
`Kokoro.create(..., is_phonemes=True)`. The one-time 2.3s moves to startup and
per-utterance phonemization becomes free.

Correctness was the risk, not speed — kokoro normalizes text and drops
out-of-vocab phonemes before inference, so both steps had to be replicated
exactly or the model would receive tokens it was never trained on. Verified
against the real library on sentences containing numbers, abbreviations and
alphanumerics (`"I found 4 files…"`, `"Dr. Smith replied at 9:30 a.m. about the
Q3 budget."`): output audio is **bit-identical** to the slow path, 4–11× faster.

If the fast path fails for any reason it falls back to kokoro's own
phonemization, so a broken espeak degrades to slow-but-working rather than
crashing the voice session.

## What remains

The agent step is now **82% of the budget** and exceeds the entire gate on its
own. No further STT/TTS tuning can close a 1.08s deficit against a 2.95s LLM
step. The remaining lever is the one the spec already calls for and we have not
built:

**Sentence-level TTS streaming (spec §5, unimplemented).** Today the pipeline
waits for the complete answer before synthesizing anything. Streaming the first
sentence to TTS as soon as the model emits it changes the measured quantity
from *total answer time* to *time-to-first-sentence*:

```
0.12s  STT
+ ~1.1s  first sentence (~15-20 tokens at the measured 13-20 tok/s)
+ 0.35s  TTS first audio
≈ 1.6s   -> PASSES with ~0.9s margin
```

This is a projection, not a measurement — it assumes a first sentence of
15–20 tokens and must be confirmed once implemented.

**The gate is therefore recorded as FAILING but achievable.** It is an unmet
acceptance criterion with a known, scoped fix — not evidence that the design
target is wrong.

## Method and caveats

`latency.py` exercises the real pipeline — actual Parakeet STT, actual agent
loop against Ollama, actual Kokoro TTS — not mocks. Five repetitions, medians
reported. Two deliberate deviations:

1. **No live microphone.** The utterance ("say hello in one short sentence") is
   synthesized once via Kokoro and fed to STT as a buffer, because the mic is
   TCC-gated and unavailable headless. This *understates* real latency slightly:
   it omits PTT key-release handling and the tail of audio capture. Both are
   small next to the 2.95s LLM cost.
2. **Warm-up excluded.** The first iteration loads both models and is discarded,
   which is correct for a p50 steady-state gate — but a cold first utterance
   after launch is materially worse, and now also pays the one-time 2.3s espeak
   backend build.

The "no-tool answer" condition is enforced by disabling the optional tool groups
(`enable_web`, `enable_apple`) so the model answers directly without a tool
round-trip. This is the easiest case; any answer requiring a tool call will be
slower.

Measured with `qwen3.8:27b`. Glimmer generates ~40% faster per token
(`docs/model-ab.md`), so the agent step would likely be lower with it — but its
tool-wandering makes it worse on tasks that do use tools.
