# Integration + live smoke — Plan 3 (voice pipeline)

**Date:** 2026-08-22
**Stack:** torch-free — `parakeet-mlx` (STT), `kokoro-onnx` (TTS), `sounddevice` + `pynput` (audio capture / global hotkey)
**Models:** `mlx-community/parakeet-tdt-0.6b-v2` (STT, HF cache), `kokoro-v1.0.onnx` + voice `af_heart` (TTS, `~/.cache/glimmer-assistant/kokoro/`)
**Agent model:** Ollama `muse-glimmer:30b` (present in `ollama list`, id `de878ce33ad8`, 18 GB)
**Platform:** macOS (Darwin), Python 3.14.6, worktree `.claude/worktrees/voice-pipeline`

This is the Plan 3 exit gate. It combines automated evidence (integration test suite,
unit suite, and a diverse-phrase accuracy sweep through the assistant's own STT/TTS
adapters) with a manual checklist for the parts that need a live microphone and OS
permissions the automated session does not have.

## Summary

| Check | Result |
|---|---|
| Integration suite (`GLIMMER_VOICE_INTEGRATION=1`, real models) | **PASS** — 2/2 |
| Full unit suite | **PASS** — 92 passed, 2 skipped |
| Diverse-phrase accuracy sweep (6 phrases, real Kokoro→Parakeet round-trip) | **PASS** — 6/6, 100% average word-accuracy, 0 weak |
| Manual mic + hotkey checklist | **NOT RUN in this session** — requires macOS Microphone + Accessibility permissions the automated agent does not have; see checklist below for the user to run |

---

## 1. Integration suite

Command:

```
GLIMMER_VOICE_INTEGRATION=1 .venv/bin/python -m pytest -m integration -v
```

Output (re-run to confirm, this session):

```
============================= test session starts ==============================
platform darwin -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- .../voice-pipeline/.venv/bin/python
collecting ... collected 94 items / 92 deselected / 2 selected

tests/test_stt_integration.py::test_tts_stt_roundtrip PASSED             [ 50%]
tests/test_tts_integration.py::test_kokoro_produces_nonsilent_audio PASSED [100%]

======================= 2 passed, 92 deselected in 8.30s =======================
```

Both tests exercise the real, non-mocked models: `test_tts_stt_roundtrip` synthesizes
speech with the assistant's `KokoroTTS` adapter and transcribes it back with the
assistant's `ParakeetSTT` adapter, and `test_kokoro_produces_nonsilent_audio` verifies
Kokoro produces genuine non-silent PCM output rather than an empty/near-zero buffer.
Both are gated behind `GLIMMER_VOICE_INTEGRATION=1` (skipped by default, per the
`pytest.mark.integration` + `skipif` in the two test files) so the unit suite stays fast
and hardware/model-free.

## 2. Full unit suite

Command:

```
.venv/bin/python -m pytest -q
```

Output (this session, no integration env var set):

```
........................................................................ [ 76%]
..........s.s.........                                                   [100%]
92 passed, 2 skipped in 0.47s
```

The 2 skipped tests are the same two integration tests above, correctly skipped in the
default (no `GLIMMER_VOICE_INTEGRATION`) run — confirming the gating works both ways
(skips by default, runs when opted in).

## 3. Diverse-phrase accuracy sweep

Six phrases spanning distinct linguistic categories (plain command, spoken numbers,
technical/path syntax, mixed punctuation, a longer natural-language request, and
application names) were round-tripped through the assistant's own `KokoroTTS` (voice
`af_heart`) → `ParakeetSTT` (`parakeet-tdt-0.6b-v2`) adapters — the exact code path the
voice session uses in production, not a standalone script. All phrases are synthetic
test strings with no real personal or corporate data.

| Category | Input phrase | Transcript | Notes |
|---|---|---|---|
| command | "what files are on my desktop" | "What files are on my desktop?" | clean |
| numbers | "set a timer for twenty five minutes and thirty seconds" | "Set a timer for 25 minutes and 30 seconds." | digit normalization, clean |
| paths-technical | "open the file config dot yaml in the assistant folder" | "Open the file config.yaml in the assistant folder." | "dot yaml" → ".yaml", clean |
| punctuation-multi | "The build passed. Are you sure? Let us ship it!" | "The build passed, are you sure? Let us ship it." | all 10 words correct; punctuation drift only |
| long-natural | "please summarize the three most recent emails and tell me if any need a reply today" | (word-perfect) | clean |
| app-names | "open calculator and then launch the notes application" | "Open Calculator, and then launch the Notes application." | clean |

**Result: 6/6 phrases, average word-accuracy 100%, 0 weak transcriptions.** Content
words were correct across every category with no substitutions, homophones, or dropped
words; the only differences from the input were cosmetic (capitalization and
punctuation choices Parakeet makes on its own output, e.g. "25" vs "twenty five",
commas Kokoro/Parakeet insert around clauses). This is strong evidence the STT/TTS
round-trip is production-quality for real voice commands, including numeric,
technical/path, and multi-sentence phrasing.

## 4. Versions

```
$ .venv/bin/python --version
Python 3.14.6

$ .venv/bin/pip show parakeet-mlx kokoro-onnx sounddevice pynput onnxruntime mlx | grep -E '^(Name|Version)'
Name: parakeet-mlx
Version: 0.5.2
Name: kokoro-onnx
Version: 0.4.7
Name: sounddevice
Version: 0.5.6
Name: pynput
Version: 1.8.2
Name: onnxruntime
Version: 1.29.0
Name: mlx
Version: 0.32.1

$ ollama --version
ollama version is 0.32.15
```

Agent model: `muse-glimmer:30b` (present locally in `ollama list`).

---

## 5. Manual mic + hotkey checklist (user-run)

The live microphone capture and global push-to-talk hotkey require macOS Microphone
and Accessibility permissions that this automated session does not have and cannot
grant itself, so `python -m assistant --voice` was **not run** in this session — the
steps below are for the user to run by hand to close out the live half of the exit
gate. Everything up to this point (STT/TTS quality, wiring, unit tests) is automated
and already verified above; this section is the remaining user-in-the-loop check.

1. Grant Microphone **and** Accessibility permission to the terminal app (System
   Settings → Privacy & Security → Microphone / Accessibility).
2. Ensure Ollama is running and serving `muse-glimmer:30b`.
3. Install the voice extra if not already present: `.venv/bin/pip install -e '.[voice]'`
4. Run `.venv/bin/python -m assistant --voice`
5. Hold Ctrl, say "what files are on my desktop", release.
   Expect: transcription appears, the agent runs `list_dir`, and a spoken answer is
   read back.
6. Hold Ctrl, say "open the calculator".
   Expect: a spoken confirmation and the Calculator app opening.
7. Hold Ctrl, ask it to run a shell command (e.g. "run a shell command to list files").
   Expect: a spoken decline along the lines of "that needs confirmation I can't take
   by voice yet" — voice mode auto-declines Tier-2 CONFIRM tools in Plan 3 by design
   (documented safety scope: no spoken-confirmation UX yet, `run_shell` and other
   CONFIRM-tier tools are unusable by voice until a future plan adds one).

**Steps 5–7 were NOT executed in this automated session** — no microphone or OS
permissions are available to the agent running this smoke test. They are left for the
user to run and confirm.

---

## Conclusion

The automated half of the Plan 3 exit gate — the integration suite, the full unit
suite, and a 6-phrase diverse-content accuracy sweep through the real STT/TTS
adapters — all pass cleanly with no substitutions or dropped content words. The
remaining live half (microphone capture, global hotkey, end-to-end voice command
execution against the running agent, and the Tier-2 auto-decline behavior) requires
macOS permissions this session does not hold and is documented above as a manual
checklist for the user to run.
