# Voice latency: spec §9 gate

**Date:** 2026-08-22
**Host:** MacBook Pro, Apple M3 Max, 128 GB, macOS 26.6.2
**Model under test:** `qwen3.8:27b` (the then-current default)
**Gate:** `docs/spec.md` §9 — *PTT release → first TTS audio ≤ 2.5s p50 for a no-tool answer.*

> ⚠️ **Measured on a throttled host.** Low Power Mode was active on battery
> (`pmset -g` → `Battery Power: powermode 1`) with load average ~21. These
> numbers are a **worst-case floor**, not the deployment target. The gate must
> be re-run on AC power with `powermode 0` on an idle machine before the result
> is treated as final. See "What this does and does not settle" below.

## Result

| Stage | Median | Share |
|---|---:|---:|
| STT (Parakeet-TDT, MLX) | 0.16s | 1.5% |
| **Agent loop (LLM)** | **8.38s** | **77.1%** |
| TTS first audio (Kokoro-82M) | 2.33s | 21.4% |
| **Total** | **10.87s** | |
| **Gate** | **≤ 2.50s** | |
| **Verdict** | ❌ **MISS by 8.37s** | |

## Method

`latency.py` exercises the **real** pipeline — actual Parakeet STT, actual agent
loop against Ollama, actual Kokoro TTS — not mocks. Five repetitions, medians
reported.

Two deliberate deviations from a literal reading of the gate:

1. **No live microphone.** The utterance ("say hello in one short sentence") is
   synthesized once via Kokoro and fed to STT as a buffer. The mic is
   user-gated behind TCC, so a headless run cannot open it. This *understates*
   real latency slightly: it omits PTT key-release handling and the tail of
   audio capture. Both are small next to the 8.38s LLM cost.
2. **Warm-up excluded.** The first iteration loads both models and is discarded.
   This is correct for a p50 steady-state gate but means a cold first utterance
   after launch will be materially worse.

The "no-tool answer" condition is enforced by disabling the optional tool groups
(`enable_web`, `enable_apple`) so the model answers directly without a tool
round-trip — the easiest case, and it still misses by 4.3×.

## Reading the result

**STT and TTS are not the problem.** Parakeet at 0.16s is comfortably inside
budget. Kokoro's 2.33s to first audio is higher than the ~90ms the spec cites,
which is worth a look, but even if it were free the gate would still fail.

**The LLM step is 77% of the budget and 3.4× the entire gate on its own.** No
amount of STT/TTS tuning closes this. The two levers that matter:

- **Sentence-level TTS streaming.** The spec (§5) already calls for streaming
  the final answer to TTS sentence-by-sentence. Measured here is
  time-to-*first*-audio against a fully-formed answer; streaming the first
  sentence as soon as it is emitted would cut perceived latency substantially
  without making the model faster. **This is the highest-value unimplemented
  optimization.**
- **Throughput.** At ~4–6 tok/s (throttled), a 40-token answer costs ~8s. This
  is exactly the measurement corrupted by Low Power Mode, and exactly why the
  re-run matters — see `docs/model-ab.md`.

## What this does and does not settle

**Settles:** the pipeline works end to end; STT is cheap; the bottleneck is
unambiguously the LLM step, not the voice stack.

**Does not settle:** whether the gate is achievable. The dominant term was
measured on throttled hardware with the spec-mandated MLX + DFlash runtime
*not* in use. Both must be corrected before declaring the ≤2.5s gate
unreachable.

### Re-run checklist

1. Connect AC power; confirm `pmset -g | grep powermode` reports `0`.
2. Quiet the machine (load average in low single digits).
3. Pull and select the spec-aligned runtime (`docs/spec.md` §2), then re-run
   `docs/model-ab.md`'s throughput benchmark to get a clean tok/s baseline.
4. Re-run `latency.py`.
5. If still failing, implement sentence-level TTS streaming and re-measure
   perceived time-to-first-audio.

Until step 4 is done, **the gate is recorded as FAILING** — an unmet acceptance
criterion, not a resolved one.
