# Voice latency: spec §9 gate

**Date:** 2026-08-22
**Host:** MacBook Pro, Apple M3 Max, 128 GB, macOS 26.6.2 — **AC power, `powermode 0`**, load ~4–6
**Model under test:** `qwen3.8:27b` (current default)
**Gate:** `docs/spec.md` §9 — *PTT release → first TTS audio ≤ 2.5s p50 for a no-tool answer.*

## Correction: 2.59s is not what users experience

The 2.59s below is real but **unrepresentative**. It was measured with the
optional tool groups disabled (`enable_web=False`, `enable_apple=False`) on the
prompt *"say hello in one short sentence"* — the easiest case the app supports.

With the real tool schema and a real question, time to the **first spoken word**
is far worse:

| turn | first spoken word | full answer |
|---|---:|---:|
| no tool — *"what can you help me with?"* | **23.9s** | 33.5s |
| one tool — *"open the calculator"* | **14.5s** | 14.5s |
| tool + ambiguity | **23.8s** | 25.7s |

Streaming does not rescue this. The model emits **all** of its reasoning before
any content, so there is nothing to stream until thinking finishes — and
reasoning is ~60% of everything generated:

| prompt | total tokens | thinking | answer |
|---|---:|---:|---:|
| "what can you help me with?" | 102 | **271 ch** | 184 ch |
| "open the calculator" | 65 | **106 ch** | 0 |

The answers are already short — the system prompt's "one or two short
sentences" is obeyed. The wait is reasoning the user never hears.

Suppressing it was measured and rejected (see below): 10/10 → 9/10 and
`</think>` leaking into speech. So the mitigation is not speed but
**acknowledgement** — the session speaks a short filler the moment the
transcript lands, so a 20-second gap stops reading as a broken app.

**Treat the §9 gate below as a floor for the easiest case, not a description of
normal use.**

## Result (easiest case, tool groups disabled)

The gate measures **PTT release → first TTS audio**. With sentence-level
streaming (spec §5) the answer is spoken as it is written, so the quantity that
counts is time-to-*first-sentence*, not time-to-complete-answer.

| Stage | Median | Share |
|---|---:|---:|
| STT (Parakeet-TDT, MLX) | 0.13s | 5% |
| **TTFT — model's first content token** | **~1.9s** | **73%** |
| first delta → first complete sentence | 0.24s | 9% |
| TTS synthesis of that sentence | 0.31s | 12% |
| **Total to first audio** | **2.59s** | |
| **Gate** | **≤ 2.50s** | |
| **Verdict** | ❌ **miss by 0.09s** | |

Measured on AC (`powermode 0`), 10 repetitions, `qwen3.8:27b`. Full answer
completes at ~2.90s; everything after the first sentence overlaps with speech
the user is already hearing and does not count against the gate.

Spoken chunking is clean in practice — `'Hello!'` / `'How can I help you
today?'` — with no broken fragments.

## How we got here

The first measurement of this gate read **10.87s**. Two defects were found and
removed, neither of which was a property of the models:

| | STT | Agent | TTS | To first audio | vs gate |
|---|---:|---:|---:|---:|---:|
| Initial measurement | 0.16s | 8.38s | 2.33s | **10.87s** | miss by 8.37s |
| …on AC power (`powermode 0`) | 0.11s | 2.85s | 2.12s | **5.08s** | miss by 2.58s |
| …with the TTS phonemizer fix | 0.12s | 2.95s | 0.51s | **3.58s** | miss by 1.08s |
| …with sentence-level streaming | 0.13s | — | — | **2.59s** | miss by 0.09s |

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

## What remains: reasoning tokens, not speed

At 0.09s short, the obvious question is where the remaining 2.59s sits. It is
**not** prompt evaluation — the prompt is ~200 tokens and Ollama reports
**0.23s / 31 tokens** for it. It is **hidden reasoning tokens**.

`qwen3.8:27b` is a reasoning model. Asked directly (bypassing the OpenAI shim),
it emits 70–80 characters of thinking before its first spoken word — even for
"say hello in one short sentence":

| | first content token | thinking emitted | tokens generated |
|---|---:|---:|---:|
| default | **1.94s** | 81 chars | 29 |
| `think=False` | **0.23s** | 0 | 3 |

**8.4×.** Disabling thinking would clear the gate outright — projected ~0.91s
against a 2.5s budget.

**It was measured, and it is rejected.** The 10-task eval was re-run on AC with
reasoning suppressed:

| | eval score | `</think>` leaked into visible text |
|---|---:|---:|
| reasoning on (default) | **10/10** | 0/22 |
| `reasoning_effort: "none"` | **9/10** | **1/10** |

Two independent reasons not to ship it:

1. **It costs task accuracy, on tool use.** `read-file` failed: without
   reasoning the model could not resolve `~`, fell back to `run_shell` (which
   the harness auto-declines), and gave up — *"the tool couldn't determine your
   home directory and the shell command to fall back on was declined"*. With
   reasoning on, the same task answers in 12.0s. This is exactly the
   tool-selection quality that decided the model choice in `docs/model-ab.md`.
2. **It leaks reasoning markers into spoken output.** Suppression does not
   cleanly remove thinking; it breaks the channel separation, and a literal
   `</think>` lands mid-answer in `content` — about 1 turn in 10. In the voice
   path that is handed to TTS and **spoken aloud**. It also rules out the
   narrower "disable thinking only on no-tool turns" variant, because both
   observed leaks were on no-tool turns.

The default configuration is clean: 0 leaks in 22 sampled turns with reasoning
on. `Config.llm_reasoning_effort` stays wired and defaults to `""` (the key is
omitted from the request entirely), so it is available for a deployment that
would trade 9/10 for the latency — but it is not the default, and it should not
be enabled for voice.

### A methodology note

The first attempt to reproduce the leak used a short ad-hoc system prompt and
passed **no tools**, and found 0/12. That result was worthless: tool presence
changes the chat template the model is rendered with, which is the machinery
that emits think markers. Reproducing it required driving the real agent loop
with the real system prompt and schemas. When a defect appears under the full
configuration, reproduce it under the full configuration.

The streaming work itself is done and is what took the gate from 10.87s to
2.59s. What is left is a model-configuration decision with a real tradeoff, not
an engineering gap.

For the record, our streaming path does **not** speak the reasoning: Ollama
reports it on a separate channel and the OpenAI shim keeps it out of `content`,
so only the answer reaches TTS. Verified in the measured runs above.

## Method and caveats

`latency_stream.py` exercises the real pipeline — actual Parakeet STT, actual
agent loop streaming from Ollama, actual Kokoro TTS — not mocks. Ten
repetitions, medians reported. (An earlier `latency.py` measured the
non-streaming path and produced the 10.87s / 5.08s / 3.58s rows above.)

Ten repetitions matters here: a five-rep run of the same script gave a median
of 2.17s, which would have read as a PASS. The wider sample moved it to 2.59s.
With a margin this thin, do not quote a five-rep number.

Two deliberate deviations:

1. **No live microphone.** The utterance ("say hello in one short sentence") is
   synthesized once via Kokoro and fed to STT as a buffer, because the mic is
   TCC-gated and unavailable headless. This *understates* real latency slightly:
   it omits PTT key-release handling and the tail of audio capture. Both are
   small next to the ~1.9s spent waiting on the model's first content token.
2. **Warm-up excluded.** The first iteration loads both models and is discarded,
   which is correct for a p50 steady-state gate — but a cold first utterance
   after launch is materially worse, and now also pays the one-time 2.3s espeak
   backend build.

The "no-tool answer" condition is enforced by disabling the optional tool groups
(`enable_web`, `enable_apple`) so the model answers directly without a tool
round-trip. This is the easiest case; any answer requiring a tool call will be
slower.

Measured with `qwen3.8:27b`. Glimmer generates ~35% faster per token
(`docs/model-ab.md`), so its time-to-first-sentence would likely be lower — but
its tool-wandering makes it worse on tasks that do use tools, and it has not
been measured against this gate.
