# Voice Pipeline Implementation Plan (Plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the assistant a voice. Hold a push-to-talk hotkey, speak a request, and the assistant transcribes it, runs the existing agent loop, and speaks the answer back — all fully local. Wraps (does not modify) the Plan-1/2 agent core.

**Architecture:** A `VoiceSession` orchestrator drives a simple loop: `PushToTalk.capture_utterance()` (pynput hotkey + sounddevice recording) → `SpeechToText.transcribe()` (Parakeet-MLX) → `AgentLoop.run()` (existing) → split the answer into sentences → `TextToSpeech.speak()` per sentence (Kokoro-ONNX → sounddevice playback). Every heavy/hardware piece sits behind a small Protocol with a fake, so the orchestrator, sentence-splitter, and wiring are unit-tested hermetically; the real model/audio adapters are integration-tested (marked) and confirmed by a live smoke.

**Tech Stack:** Python ≥3.12 (runs on 3.14.6), **torch-free**: `parakeet-mlx` (STT, MLX/Metal), `kokoro-onnx` (TTS, ONNX/CoreML), `sounddevice` (audio I/O), `pynput` (global hotkey), `soundfile`, `numpy`. All in an optional `[voice]` extra; lazy-imported so text mode still runs without them.

**Spec:** `docs/spec.md` §5 (voice pipeline). Implements push-to-talk activation, Parakeet STT, Kokoro TTS, sentence-by-sentence spoken output.

## Foundation verified before planning (2026-08-22, this machine)

- Python 3.14.6, macOS 26.6.2 arm64 (M3 Max). All voice deps install with wheels for 3.14; **no torch anywhere**.
- Imports confirmed: `mlx` (Metal=True), `onnxruntime` (CoreMLExecutionProvider), `parakeet_mlx`, `kokoro_onnx`, `sounddevice`, `pynput`.
- **End-to-end round-trip PASSED**: `Kokoro(onnx,voices).create("the quick brown fox...", voice="af_heart")` → 24kHz audio → `from_pretrained("mlx-community/parakeet-tdt-0.6b-v2").transcribe(wav).text` → `"the quick brown fox jumps over the lazy dog."` (5/5 keywords, exact).
- Kokoro model files (already downloaded to `~/.cache/glimmer-voice-probe/`): `kokoro-v1.0.onnx` (310MB), `voices-v1.0.bin` (26MB), from `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/`. Parakeet auto-downloads from HuggingFace.

## Scope boundary (read before starting)

IN: push-to-talk, Parakeet STT, Kokoro TTS, sentence-by-sentence spoken replies, `--voice` entry point, model download/caching.
DEFERRED (noted at seams, no consumer yet): Silero **VAD** (torch-based; push-to-talk needs no silence detection — an ONNX-VAD enhancement can come later); **streaming STT during hold** (Parakeet transcribes a full clip in ~50-200ms, fast enough for v1 — streaming is a latency optimization); **wake word** (openWakeWord, Plan 5+); **Windows audio/hotkey** (parity later — the adapters are behind Protocols so a Windows adapter drops in). Building these now means building against no v1 need.

## Global Constraints

- Python ≥3.12; package `assistant`; worktree root is project root. Voice deps live ONLY in the `[voice]` optional extra — the core (`openai`, `pyyaml`) gains nothing. Voice modules lazy-import their heavy deps so `python -m assistant` (text mode) works with the base install.
- **Unit tests are hermetic and fast**: never load a real model, never open an audio device, never hit the network. Heavy adapters are tested via fakes or marked integration tests.
- **Integration tests** (real Parakeet/Kokoro models, no audio device) are marked `@pytest.mark.integration` and skipped unless `GLIMMER_VOICE_INTEGRATION=1` is set. They reuse cached models; they must not require a microphone or speakers.
- Model files cache at `~/.cache/glimmer-assistant/` (Kokoro files) and the HF cache (Parakeet). Defaults: STT model `mlx-community/parakeet-tdt-0.6b-v2`, TTS voice `af_heart`, Kokoro sample rate 24000.
- Audio format between components: mono `float32` numpy array + an int sample rate, passed explicitly (never a global).
- Run tests with `.venv/bin/python -m pytest` (unit) and `GLIMMER_VOICE_INTEGRATION=1 .venv/bin/python -m pytest -m integration` (integration). Commit after every green cycle.
- Reuse the already-downloaded Kokoro files: before integration tasks, they will be present at `~/.cache/glimmer-assistant/kokoro/` (the controller seeds them from the probe cache).

---

### Task 1: Voice package, optional deps, interfaces, config

**Files:**
- Modify: `pyproject.toml` (add `[project.optional-dependencies] voice = [...]` and a pytest `integration` marker)
- Create: `assistant/voice/__init__.py` (empty)
- Create: `assistant/voice/interfaces.py`
- Modify: `assistant/config.py`
- Test: `tests/test_config.py` (add), `tests/test_voice_interfaces.py` (new)

**Interfaces:**
- Consumes: `Config` (Plan 1).
- Produces:
  - In `interfaces.py`, three `typing.Protocol` classes (runtime-checkable): `SpeechToText` with `transcribe(self, audio: "np.ndarray", sample_rate: int) -> str`; `TextToSpeech` with `speak(self, text: str) -> None`; `PushToTalk` with `capture_utterance(self) -> tuple["np.ndarray", int] | None` (returns audio+sr, or None if the press was too short to be speech). Use `from __future__ import annotations` and a `TYPE_CHECKING` import for numpy so importing `interfaces` needs no numpy at runtime.
  - `Config` gains: `voice_stt_model: str = "mlx-community/parakeet-tdt-0.6b-v2"`, `voice_tts_voice: str = "af_heart"`, `voice_hotkey: str = "ctrl"`, `voice_min_utterance_seconds: float = 0.3`.

- [ ] **Step 1: Add the pytest integration marker and voice extra**

In `pyproject.toml`, under `[project.optional-dependencies]` add:

```toml
voice = [
    "parakeet-mlx>=0.5",
    "kokoro-onnx>=0.4",
    "sounddevice>=0.5",
    "pynput>=1.8",
    "soundfile>=0.13",
    "numpy>=2.0",
]
```

Under `[tool.pytest.ini_options]` add a markers entry:

```toml
markers = ["integration: needs real voice models (set GLIMMER_VOICE_INTEGRATION=1)"]
```

Install the extra: `.venv/bin/pip install -e '.[dev,voice]'` (models already cached; this just wires the extra).

- [ ] **Step 2: Write the failing tests**

`tests/test_voice_interfaces.py`:

```python
from assistant.voice.interfaces import PushToTalk, SpeechToText, TextToSpeech


def test_protocols_are_importable_without_numpy_installed():
    # importing interfaces must not import numpy/heavy deps
    assert hasattr(SpeechToText, "transcribe")
    assert hasattr(TextToSpeech, "speak")
    assert hasattr(PushToTalk, "capture_utterance")


def test_duck_typed_impl_satisfies_protocol():
    class FakeSTT:
        def transcribe(self, audio, sample_rate):
            return "hi"

    assert isinstance(FakeSTT(), SpeechToText)
```

Add to `tests/test_config.py`:

```python
def test_voice_config_defaults():
    cfg = load_config(None)
    assert cfg.voice_stt_model == "mlx-community/parakeet-tdt-0.6b-v2"
    assert cfg.voice_tts_voice == "af_heart"
    assert cfg.voice_hotkey == "ctrl"
    assert cfg.voice_min_utterance_seconds == 0.3
```

- [ ] **Step 2b: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_voice_interfaces.py tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError`).

- [ ] **Step 3: Implement interfaces.py and config fields**

`assistant/voice/interfaces.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(self, audio: "np.ndarray", sample_rate: int) -> str: ...


@runtime_checkable
class TextToSpeech(Protocol):
    def speak(self, text: str) -> None: ...


@runtime_checkable
class PushToTalk(Protocol):
    def capture_utterance(self) -> "tuple[np.ndarray, int] | None": ...
```

In `assistant/config.py`, add the four fields to `Config` (beside existing fields):

```python
    voice_stt_model: str = "mlx-community/parakeet-tdt-0.6b-v2"
    voice_tts_voice: str = "af_heart"
    voice_hotkey: str = "ctrl"
    voice_min_utterance_seconds: float = 0.3
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_voice_interfaces.py tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml assistant/voice/ assistant/config.py tests/test_voice_interfaces.py tests/test_config.py
git commit -m "feat: voice package scaffold, [voice] extra, interfaces, config"
```

---

### Task 2: Sentence splitter for streaming TTS

**Files:**
- Create: `assistant/voice/streaming.py`
- Test: `tests/test_streaming.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: `split_sentences(text: str) -> list[str]` — splits on sentence-ending punctuation (`.`, `!`, `?`) followed by whitespace/end, keeping the punctuation, trimming whitespace, dropping empties. So a long answer can be spoken sentence-by-sentence (first audio starts before the whole reply is synthesized). Pure, stdlib only.

- [ ] **Step 1: Write the failing test**

`tests/test_streaming.py`:

```python
from assistant.voice.streaming import split_sentences


def test_splits_multiple_sentences():
    assert split_sentences("Hello there. How are you? I am fine!") == [
        "Hello there.",
        "How are you?",
        "I am fine!",
    ]


def test_single_sentence_no_terminator():
    assert split_sentences("just one clause") == ["just one clause"]


def test_empty_and_whitespace():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_collapses_internal_whitespace_runs_but_keeps_sentences():
    assert split_sentences("A.\n\nB.") == ["A.", "B."]
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_streaming.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement streaming.py**

`assistant/voice/streaming.py`:

```python
from __future__ import annotations

import re

_SENTENCE = re.compile(r"[^.!?]*[.!?]+|\S[^.!?]*$")


def split_sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE.finditer(text) if m.group().strip()]
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_streaming.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add assistant/voice/streaming.py tests/test_streaming.py
git commit -m "feat: sentence splitter for streaming TTS"
```

---

### Task 3: VoiceSession orchestrator

**Files:**
- Create: `assistant/voice/session.py`
- Test: `tests/test_voice_session.py` (new)

**Interfaces:**
- Consumes: `SpeechToText`, `TextToSpeech`, `PushToTalk` (Task 1), `split_sentences` (Task 2), and any object with `.run(text: str) -> str` (the existing `AgentLoop`).
- Produces: `VoiceSession(ptt, stt, agent, tts, min_utterance_seconds: float = 0.3, on_event=None)` with `run_once() -> bool` (handle one utterance; returns False when the ptt signals shutdown by returning a sentinel — see below) and `run_forever() -> None`. Flow per utterance: `capture_utterance()`; if None → return True (ignore, keep listening); else transcribe → if transcript is blank, skip; else `agent.run(transcript)` → for each sentence in `split_sentences(reply)`: `tts.speak(sentence)`. Any exception from transcribe/agent/tts is caught, spoken as a short error ("Sorry, something went wrong.") via tts, and swallowed so the session keeps listening. `on_event(name, payload)` optional callback fires for `"listening"`, `"transcribed"`, `"answered"`, `"error"` (for a UI/log; default no-op). `run_forever` loops `run_once` until it returns False. The ptt returning the sentinel `PushToTalk.STOP` (a module-level object) ends the loop.

Wait — to keep `capture_utterance` return typed simply (`tuple|None`), model shutdown differently: `run_forever` runs until `KeyboardInterrupt`. Drop the sentinel. `run_once()` returns None; `run_forever()` loops `run_once()` inside `try/except KeyboardInterrupt: return`.

- [ ] **Step 1: Write the failing tests**

`tests/test_voice_session.py`:

```python
import numpy as np

from assistant.voice.session import VoiceSession


class FakePTT:
    def __init__(self, utterances):
        self._utterances = list(utterances)

    def capture_utterance(self):
        return self._utterances.pop(0)


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def transcribe(self, audio, sample_rate):
        self.calls.append((audio, sample_rate))
        return self.text


class FakeAgent:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def run(self, text):
        self.prompts.append(text)
        return self.reply


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def audio():
    return (np.zeros(8000, dtype="float32"), 16000)


def test_full_utterance_flow():
    ptt = FakePTT([audio()])
    stt = FakeSTT("what is on my desktop")
    agent = FakeAgent("You have three files. They are small.")
    tts = FakeTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()

    assert stt.calls[0][1] == 16000
    assert agent.prompts == ["what is on my desktop"]
    # answer spoken sentence-by-sentence
    assert tts.spoken == ["You have three files.", "They are small."]


def test_none_utterance_is_ignored():
    ptt = FakePTT([None])
    stt = FakeSTT("unused")
    agent = FakeAgent("unused")
    tts = FakeTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()

    assert agent.prompts == []
    assert tts.spoken == []


def test_blank_transcript_skips_agent():
    ptt = FakePTT([audio()])
    session = VoiceSession(ptt, FakeSTT("   "), FakeAgent("x"), FakeTTS())
    session.run_once()
    # agent never called on empty transcription
    assert session._agent.prompts == []


def test_agent_error_is_spoken_not_raised():
    class BoomAgent:
        def run(self, text):
            raise RuntimeError("kaboom")

    ptt = FakePTT([audio()])
    tts = FakeTTS()
    session = VoiceSession(ptt, FakeSTT("hi"), BoomAgent(), tts)

    session.run_once()  # must not raise

    assert any("something went wrong" in s.lower() for s in tts.spoken)


def test_run_forever_stops_on_keyboard_interrupt():
    class InterruptingPTT:
        def capture_utterance(self):
            raise KeyboardInterrupt

    session = VoiceSession(InterruptingPTT(), FakeSTT("x"), FakeAgent("y"), FakeTTS())
    session.run_forever()  # returns cleanly, does not propagate
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_voice_session.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement session.py**

`assistant/voice/session.py`:

```python
from __future__ import annotations

from typing import Callable

from assistant.voice.streaming import split_sentences

_ERROR_SPEECH = "Sorry, something went wrong."


class VoiceSession:
    def __init__(
        self,
        ptt,
        stt,
        agent,
        tts,
        min_utterance_seconds: float = 0.3,
        on_event: Callable[[str, object], None] | None = None,
    ):
        self._ptt = ptt
        self._stt = stt
        self._agent = agent
        self._tts = tts
        self._min_seconds = min_utterance_seconds
        self._on_event = on_event or (lambda name, payload: None)

    def run_once(self) -> None:
        self._on_event("listening", None)
        captured = self._ptt.capture_utterance()
        if captured is None:
            return
        audio, sample_rate = captured
        try:
            transcript = self._stt.transcribe(audio, sample_rate).strip()
            if not transcript:
                return
            self._on_event("transcribed", transcript)
            reply = self._agent.run(transcript)
            self._on_event("answered", reply)
            for sentence in split_sentences(reply):
                self._tts.speak(sentence)
        except Exception as e:  # a bad turn must not kill the session
            self._on_event("error", e)
            self._tts.speak(_ERROR_SPEECH)

    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
        except KeyboardInterrupt:
            return
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_voice_session.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add assistant/voice/session.py tests/test_voice_session.py
git commit -m "feat: VoiceSession orchestrator (hermetic, fake-tested)"
```

---

### Task 4: Kokoro TTS adapter + model downloader

**Files:**
- Create: `assistant/voice/models.py`
- Create: `assistant/voice/tts.py`
- Test: `tests/test_models.py` (new), `tests/test_tts_integration.py` (new, marked)

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `models.py`: `KOKORO_DIR = Path("~/.cache/glimmer-assistant/kokoro").expanduser()`; `ensure_kokoro_models() -> tuple[Path, Path]` returns `(onnx_path, voices_path)`, downloading each from the pinned release URL only if absent/empty (uses `urllib.request`); `_download(url, dest)` helper. Pinned base URL `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/`, files `kokoro-v1.0.onnx`, `voices-v1.0.bin`.
  - `tts.py`: `KokoroTTS(voice: str, *, kokoro=None, player=None)` implementing `TextToSpeech`. Lazy-imports `kokoro_onnx` and `sounddevice` inside `__init__`/`speak` (so importing the module is cheap). If `kokoro` is None, builds `kokoro_onnx.Kokoro(*ensure_kokoro_models())`. `speak(text)`: `audio, sr = self._kokoro.create(text, voice=self._voice, speed=1.0, lang="en-us")`; then `self._play(audio, sr)` where `_play` defaults to `sounddevice.play(audio, sr); sounddevice.wait()`. The `kokoro`/`player` injection seams keep tests off the real model/device.

- [ ] **Step 1: Write the failing downloader test**

`tests/test_models.py`:

```python
from pathlib import Path

from assistant.voice import models


def test_ensure_kokoro_skips_download_when_present(tmp_path, monkeypatch):
    onnx = tmp_path / "kokoro-v1.0.onnx"
    voices = tmp_path / "voices-v1.0.bin"
    onnx.write_bytes(b"x" * 10)
    voices.write_bytes(b"y" * 10)
    monkeypatch.setattr(models, "KOKORO_DIR", tmp_path)

    calls = []
    monkeypatch.setattr(models, "_download", lambda url, dest: calls.append(url))

    got_onnx, got_voices = models.ensure_kokoro_models()
    assert got_onnx == onnx and got_voices == voices
    assert calls == []  # nothing downloaded, files already present


def test_ensure_kokoro_downloads_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "KOKORO_DIR", tmp_path)
    downloaded = []

    def fake_dl(url, dest):
        Path(dest).write_bytes(b"data")
        downloaded.append(Path(dest).name)

    monkeypatch.setattr(models, "_download", fake_dl)
    models.ensure_kokoro_models()
    assert set(downloaded) == {"kokoro-v1.0.onnx", "voices-v1.0.bin"}
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement models.py**

`assistant/voice/models.py`:

```python
from __future__ import annotations

import urllib.request
from pathlib import Path

KOKORO_DIR = Path("~/.cache/glimmer-assistant/kokoro").expanduser()
_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def ensure_kokoro_models() -> tuple[Path, Path]:
    paths = []
    for name in _FILES:
        dest = KOKORO_DIR / name
        if not (dest.exists() and dest.stat().st_size > 0):
            _download(_BASE + name, dest)
        paths.append(dest)
    return paths[0], paths[1]
```

- [ ] **Step 4: Run downloader test to verify pass**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Implement tts.py**

`assistant/voice/tts.py`:

```python
from __future__ import annotations

from assistant.voice.models import ensure_kokoro_models


class KokoroTTS:
    def __init__(self, voice: str, *, kokoro=None, player=None):
        if kokoro is None:
            from kokoro_onnx import Kokoro

            onnx_path, voices_path = ensure_kokoro_models()
            kokoro = Kokoro(str(onnx_path), str(voices_path))
        self._kokoro = kokoro
        self._voice = voice
        self._play = player or self._default_player

    @staticmethod
    def _default_player(audio, sample_rate: int) -> None:
        import sounddevice

        sounddevice.play(audio, sample_rate)
        sounddevice.wait()

    def speak(self, text: str) -> None:
        audio, sample_rate = self._kokoro.create(
            text, voice=self._voice, speed=1.0, lang="en-us"
        )
        self._play(audio, sample_rate)
```

- [ ] **Step 6: Write a fake-injected unit test + a marked integration test**

Add to `tests/test_models.py` (or a new `tests/test_tts.py`) a hermetic unit test using injection:

```python
def test_kokoro_tts_speaks_via_injected_kokoro_and_player():
    from assistant.voice.tts import KokoroTTS

    class FakeKokoro:
        def create(self, text, voice, speed, lang):
            return ([0.0, 0.1, 0.0], 24000)

    played = []
    tts = KokoroTTS("af_heart", kokoro=FakeKokoro(), player=lambda a, sr: played.append((a, sr)))
    tts.speak("hello")
    assert played and played[0][1] == 24000
```

`tests/test_tts_integration.py` (real model, no audio device — inject a no-op player):

```python
import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_VOICE_INTEGRATION") != "1",
    reason="set GLIMMER_VOICE_INTEGRATION=1 to run voice integration tests",
)


@skip
def test_kokoro_produces_nonsilent_audio():
    from assistant.voice.tts import KokoroTTS

    captured = {}
    tts = KokoroTTS("af_heart", player=lambda a, sr: captured.update(audio=np.asarray(a), sr=sr))
    tts.speak("testing the local text to speech engine")
    assert captured["sr"] == 24000
    assert captured["audio"].size > 24000  # >1s of audio
    assert float(np.abs(captured["audio"]).max()) > 0.01  # not silence
```

- [ ] **Step 7: Run unit tests (integration skipped by default)**

Run: `.venv/bin/python -m pytest tests/test_models.py tests/test_tts_integration.py -v`
Expected: unit tests PASS, integration test SKIPPED.

- [ ] **Step 8: Commit**

```bash
git add assistant/voice/models.py assistant/voice/tts.py tests/test_models.py tests/test_tts_integration.py
git commit -m "feat: Kokoro TTS adapter + model downloader"
```

---

### Task 5: Parakeet STT adapter

**Files:**
- Create: `assistant/voice/stt.py`
- Test: `tests/test_stt.py` (new, unit), `tests/test_stt_integration.py` (new, marked)

**Interfaces:**
- Consumes: `Config` (Task 1), `KokoroTTS` (Task 4, only in the integration round-trip test).
- Produces: `ParakeetSTT(model_id: str, *, model=None)` implementing `SpeechToText`. Lazy-imports `parakeet_mlx` and `soundfile` inside `__init__`/`transcribe`. If `model` is None, `model = parakeet_mlx.from_pretrained(model_id)`. `transcribe(audio, sample_rate) -> str`: writes the float32 array to a temp WAV via `soundfile` (Parakeet's `.transcribe` takes a path), calls `self._model.transcribe(wav_path)`, returns `result.text.strip()`. Temp file removed after.

- [ ] **Step 1: Write the failing unit test (injected fake model)**

`tests/test_stt.py`:

```python
import numpy as np


def test_parakeet_transcribe_uses_model_and_returns_text(monkeypatch, tmp_path):
    from assistant.voice.stt import ParakeetSTT

    class FakeResult:
        text = "  hello world  "

    class FakeModel:
        def __init__(self):
            self.paths = []

        def transcribe(self, path):
            self.paths.append(path)
            return FakeResult()

    fake = FakeModel()
    stt = ParakeetSTT("some/model", model=fake)
    out = stt.transcribe(np.zeros(16000, dtype="float32"), 16000)
    assert out == "hello world"  # trimmed
    assert fake.paths and str(fake.paths[0]).endswith(".wav")
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_stt.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement stt.py**

`assistant/voice/stt.py`:

```python
from __future__ import annotations

import tempfile
from pathlib import Path


class ParakeetSTT:
    def __init__(self, model_id: str, *, model=None):
        if model is None:
            import parakeet_mlx

            model = parakeet_mlx.from_pretrained(model_id)
        self._model = model

    def transcribe(self, audio, sample_rate: int) -> str:
        import soundfile

        tmp = Path(tempfile.mkstemp(suffix=".wav", prefix="glimmer-stt-")[1])
        try:
            soundfile.write(str(tmp), audio, sample_rate)
            result = self._model.transcribe(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        text = getattr(result, "text", str(result))
        return text.strip()
```

- [ ] **Step 4: Run unit test to verify pass**

Run: `.venv/bin/python -m pytest tests/test_stt.py -v`
Expected: PASS.

- [ ] **Step 5: Write the marked round-trip integration test**

`tests/test_stt_integration.py` (this is the exact TTS→STT round-trip proven in recon):

```python
import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_VOICE_INTEGRATION") != "1",
    reason="set GLIMMER_VOICE_INTEGRATION=1 to run voice integration tests",
)


@skip
def test_tts_stt_roundtrip():
    from assistant.voice.stt import ParakeetSTT
    from assistant.voice.tts import KokoroTTS

    captured = {}
    tts = KokoroTTS("af_heart", player=lambda a, sr: captured.update(audio=np.asarray(a, dtype="float32"), sr=sr))
    tts.speak("the quick brown fox jumps over the lazy dog")

    stt = ParakeetSTT("mlx-community/parakeet-tdt-0.6b-v2")
    transcript = stt.transcribe(captured["audio"], captured["sr"]).lower()

    hits = sum(w in transcript for w in ["quick", "brown", "fox", "lazy", "dog"])
    assert hits >= 3, f"round-trip transcript was: {transcript!r}"
```

- [ ] **Step 6: Run unit (integration skipped)**

Run: `.venv/bin/python -m pytest tests/test_stt.py tests/test_stt_integration.py -v`
Expected: unit PASS, integration SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add assistant/voice/stt.py tests/test_stt.py tests/test_stt_integration.py
git commit -m "feat: Parakeet STT adapter + TTS-STT round-trip integration test"
```

---

### Task 6: Audio capture + push-to-talk (hotkey + recorder)

**Files:**
- Create: `assistant/voice/audio.py`
- Test: `tests/test_audio.py` (new, unit with a fake stream)

**Interfaces:**
- Consumes: `PushToTalk` protocol (Task 1).
- Produces: `HotkeyPushToTalk(hotkey: str = "ctrl", sample_rate: int = 16000, min_seconds: float = 0.3, *, recorder_factory=None, listener_factory=None)` implementing `PushToTalk`. `capture_utterance()` blocks until the user presses the hotkey, records mono float32 at `sample_rate` while held, stops on release, and returns `(audio, sample_rate)` — or `None` if the clip is shorter than `min_seconds`. The pynput listener and sounddevice InputStream are built via the injected factories (defaulting to real ones) so the frame-assembly + min-length logic is unit-tested with fakes and no hardware. Provide a pure helper `assemble(frames: list[np.ndarray]) -> np.ndarray` (concatenate, or empty array) that is directly unit-tested.
  - Real factories: `_default_recorder_factory` returns an object wrapping `sounddevice.InputStream(samplerate, channels=1, dtype="float32", callback=...)` that appends callback frames to a list while active; `_default_listener_factory` returns a `pynput.keyboard.Listener` mapping the configured key to start/stop.

Note: the real hotkey needs macOS Accessibility permission and the mic needs Microphone permission — both are granted by the user (Task 8 live smoke). The unit tests here never touch real hardware.

- [ ] **Step 1: Write the failing tests (fake stream + fake listener)**

`tests/test_audio.py`:

```python
import numpy as np

from assistant.voice.audio import HotkeyPushToTalk, assemble


def test_assemble_concatenates_frames():
    out = assemble([np.array([1.0, 2.0], dtype="float32"), np.array([3.0], dtype="float32")])
    assert out.tolist() == [1.0, 2.0, 3.0]


def test_assemble_empty_is_empty_array():
    out = assemble([])
    assert out.size == 0


class FakeRecorder:
    """Records fixed frames while 'active'; driven by the listener fake below."""

    def __init__(self, frames):
        self._frames = frames
        self.buffer = []
        self.active = False

    def start(self):
        self.active = True
        self.buffer.extend(self._frames)  # simulate frames arriving during the hold

    def stop(self):
        self.active = False


class FakeListener:
    """Immediately simulates one press+release cycle when waited on."""

    def __init__(self, on_press, on_release):
        self._on_press = on_press
        self._on_release = on_release

    def run_one_cycle(self):
        self._on_press()
        self._on_release()


def test_capture_returns_audio_for_long_enough_hold(monkeypatch):
    # 0.5s at 16kHz = 8000 samples > min 0.3s
    frames = [np.zeros(8000, dtype="float32")]
    rec = FakeRecorder(frames)

    ptt = HotkeyPushToTalk(
        sample_rate=16000,
        min_seconds=0.3,
        recorder_factory=lambda sr, cb: rec,
        listener_factory=lambda on_press, on_release: FakeListener(on_press, on_release),
    )
    # drive one cycle synchronously via the injected listener
    result = ptt._capture_with(rec, FakeListener)  # see impl note
    ...
```

Implementation note for the engineer: the hardware-threaded design is awkward to test through the public `capture_utterance()` directly. Structure the class so the testable core is a method `_run_cycle(recorder, wait_for_release) -> tuple[np.ndarray, int] | None` that: starts the recorder, calls `wait_for_release()` (a blocking callable), stops the recorder, assembles `recorder.buffer`, and returns `(audio, sample_rate)` if `len(audio) >= min_seconds * sample_rate` else `None`. Unit-test `_run_cycle` with a `FakeRecorder` and a `wait_for_release` that returns immediately. `capture_utterance()` wires the real listener/recorder to `_run_cycle`. Rewrite the test to target `_run_cycle`:

```python
def test_run_cycle_returns_audio_when_long_enough():
    rec = FakeRecorder([np.zeros(8000, dtype="float32")])
    ptt = HotkeyPushToTalk(sample_rate=16000, min_seconds=0.3)
    got = ptt._run_cycle(rec, wait_for_release=lambda: None)
    assert got is not None
    audio, sr = got
    assert sr == 16000 and audio.size == 8000


def test_run_cycle_returns_none_when_too_short():
    rec = FakeRecorder([np.zeros(1000, dtype="float32")])  # ~0.06s < 0.3s
    ptt = HotkeyPushToTalk(sample_rate=16000, min_seconds=0.3)
    assert ptt._run_cycle(rec, wait_for_release=lambda: None) is None
```

Use ONLY the `_run_cycle`-targeted tests plus the two `assemble` tests. Drop the awkward first draft.

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_audio.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement audio.py**

`assistant/voice/audio.py`:

```python
from __future__ import annotations

import threading

import numpy as np


def assemble(frames: list[np.ndarray]) -> np.ndarray:
    if not frames:
        return np.empty(0, dtype="float32")
    return np.concatenate(frames).astype("float32")


class _Recorder:
    """Wraps a sounddevice InputStream, buffering mono float32 frames while open."""

    def __init__(self, sample_rate: int):
        self._sample_rate = sample_rate
        self.buffer: list[np.ndarray] = []
        self._stream = None

    def start(self) -> None:
        import sounddevice

        def callback(indata, frames, time_info, status):
            self.buffer.append(indata[:, 0].copy())

        self._stream = sounddevice.InputStream(
            samplerate=self._sample_rate, channels=1, dtype="float32", callback=callback
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class HotkeyPushToTalk:
    def __init__(
        self,
        hotkey: str = "ctrl",
        sample_rate: int = 16000,
        min_seconds: float = 0.3,
        *,
        recorder_factory=None,
        listener_factory=None,
    ):
        self._hotkey = hotkey
        self._sample_rate = sample_rate
        self._min_seconds = min_seconds
        self._recorder_factory = recorder_factory or (lambda sr: _Recorder(sr))
        self._listener_factory = listener_factory

    def _run_cycle(self, recorder, wait_for_release) -> "tuple[np.ndarray, int] | None":
        recorder.start()
        try:
            wait_for_release()
        finally:
            recorder.stop()
        audio = assemble(recorder.buffer)
        if audio.size < int(self._min_seconds * self._sample_rate):
            return None
        return audio, self._sample_rate

    def capture_utterance(self) -> "tuple[np.ndarray, int] | None":
        from pynput import keyboard

        released = threading.Event()
        pressed = threading.Event()

        target = getattr(keyboard.Key, self._hotkey, None)

        def on_press(key):
            if key == target:
                pressed.set()

        def on_release(key):
            if key == target and pressed.is_set():
                released.set()
                return False  # stop listener

        recorder = self._recorder_factory(self._sample_rate)
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            pressed.wait()  # block until the hotkey goes down
            return self._run_cycle(recorder, wait_for_release=released.wait)
```

(The `listener_factory` param is retained for future substitution but `capture_utterance` uses the real pynput listener; only `_run_cycle` — the assembled-audio logic — is unit-tested. Note this in the report.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_audio.py -v`
Expected: PASS (assemble ×2, _run_cycle ×2).

- [ ] **Step 5: Commit**

```bash
git add assistant/voice/audio.py tests/test_audio.py
git commit -m "feat: push-to-talk hotkey + audio capture (testable core)"
```

---

### Task 7: Voice entry point (`--voice`)

**Files:**
- Modify: `assistant/main.py`
- Test: `tests/test_main.py` (add)

**Interfaces:**
- Consumes: everything above + `build_loop` (Plan 1).
- Produces: `build_voice_session(cfg, platform, *, stt=None, tts=None, ptt=None) -> VoiceSession` in `main.py` — builds the agent loop (auto-confirmer that speaks/asks? no: for voice v1, CONFIRM-tier tools are auto-denied with a spoken note, since there's no spoken confirm UX yet — pass a confirmer that returns False and rely on the "declined" path) and, unless injected, the real `ParakeetSTT(cfg.voice_stt_model)`, `KokoroTTS(cfg.voice_tts_voice)`, `HotkeyPushToTalk(cfg.voice_hotkey, min_seconds=cfg.voice_min_utterance_seconds)`. The injection params keep the builder unit-testable without models/hardware. `main()` gains: if `--voice` in argv, build the session and `run_forever()`; else the existing text REPL.

Decision (documented): in voice mode, Tier-2 CONFIRM tools (run_shell) are auto-declined with a spoken "That needs confirmation I can't take by voice yet," because a spoken/gestural confirm flow is out of scope for Plan 3. Read-only and Tier-1 tools work normally. This keeps voice safe without a half-built spoken-confirm UX.

- [ ] **Step 1: Write the failing test (injected fakes, no hardware/models)**

Add to `tests/test_main.py`:

```python
def test_build_voice_session_wires_components(tmp_path):
    from assistant.config import Config
    from assistant.main import build_voice_session

    class FakePTT:
        def capture_utterance(self):
            return None

    class FakeSTT:
        def transcribe(self, audio, sr):
            return ""

    class FakeTTS:
        def speak(self, text):
            pass

    cfg = Config(allowed_roots=[str(tmp_path)], log_path=str(tmp_path / "a.jsonl"))
    session = build_voice_session(
        cfg, platform="darwin", stt=FakeSTT(), tts=FakeTTS(), ptt=FakePTT()
    )
    # smoke: one cycle with a None utterance does nothing and does not raise
    session.run_once()
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/python -m pytest tests/test_main.py::test_build_voice_session_wires_components -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement build_voice_session + --voice in main.py**

Read `assistant/main.py`. Add:

```python
def _voice_declines(request) -> bool:
    # Tier-2 CONFIRM tools cannot be confirmed by voice in Plan 3; decline safely.
    return False


def build_voice_session(cfg, platform, *, stt=None, tts=None, ptt=None):
    from assistant.voice.session import VoiceSession

    loop = build_loop(cfg, _voice_declines, platform)
    if stt is None:
        from assistant.voice.stt import ParakeetSTT

        stt = ParakeetSTT(cfg.voice_stt_model)
    if tts is None:
        from assistant.voice.tts import KokoroTTS

        tts = KokoroTTS(cfg.voice_tts_voice)
    if ptt is None:
        from assistant.voice.audio import HotkeyPushToTalk

        ptt = HotkeyPushToTalk(cfg.voice_hotkey, min_seconds=cfg.voice_min_utterance_seconds)
    return VoiceSession(loop, stt=stt, agent=loop, tts=tts, min_utterance_seconds=cfg.voice_min_utterance_seconds)
```

Wait — VoiceSession's first positional is `ptt`, not `loop`. Correct the constructor call:

```python
    return VoiceSession(ptt, stt, loop, tts, min_utterance_seconds=cfg.voice_min_utterance_seconds)
```

In `main()`, branch on the flag:

```python
def main() -> None:
    import sys

    config_path = Path(__file__).parent / "config.yaml"
    cfg = load_config(config_path if config_path.exists() else None)

    if "--voice" in sys.argv:
        session = build_voice_session(cfg, sys.platform)
        print("glimmer-assistant voice mode. Hold the hotkey to talk. Ctrl-C to exit.")
        session.run_forever()
        return

    loop = build_loop(cfg, cli_confirm, sys.platform)
    print("glimmer-assistant text mode. Ctrl-D to exit.")
    ...  # existing REPL unchanged
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_main.py -v && .venv/bin/python -m pytest -q`
Expected: PASS; whole unit suite green.

- [ ] **Step 5: Commit**

```bash
git add assistant/main.py tests/test_main.py
git commit -m "feat: --voice entry point wiring VoiceSession"
```

---

### Task 8: Integration + live smoke (manual gate)

**Files:**
- Create: `docs/smoke-test-plan3.md`

**Interfaces:**
- Consumes: the finished voice stack.
- Produces: the exit-gate record — automated model round-trip PASS + a documented user-in-the-loop mic/hotkey result.

- [ ] **Step 1: Run the integration suite (real models, no mic needed)**

```bash
GLIMMER_VOICE_INTEGRATION=1 .venv/bin/python -m pytest -m integration -v
```

Expected: the TTS non-silent test and the TTS→STT round-trip test PASS (models are cached). If a model file is missing it downloads once. Record the transcript the round-trip produced.

- [ ] **Step 2: Document the manual mic/hotkey checklist**

The live mic + global hotkey need user-granted macOS permissions and can't be automated. Write the checklist the user runs:
1. Grant **Microphone** and **Accessibility** permission to the terminal app (System Settings → Privacy & Security).
2. Ensure Ollama is up with `muse-glimmer:30b`.
3. `.venv/bin/python -m assistant --voice`
4. Hold **Ctrl**, say "what files are on my desktop", release. Expect: transcription → agent runs `list_dir` → a spoken answer.
5. Hold Ctrl, say "open the calculator", release. Expect: spoken confirmation of the app opening.
6. Hold Ctrl, say "run a shell command to list slash etc". Expect: a spoken "that needs confirmation I can't take by voice yet" (Tier-2 auto-declined).

- [ ] **Step 3: Record results**

Write `docs/smoke-test-plan3.md`: date, model tag, Ollama + package versions, the integration round-trip transcript (PASS/FAIL), and — if the user ran the manual steps — their observations (latency to first spoken word, transcription accuracy). Redact any real personal/corporate file names from transcripts (replace with placeholders). Honest results only.

- [ ] **Step 4: Commit**

```bash
git add docs/smoke-test-plan3.md
git commit -m "docs: Plan 3 voice integration + live smoke results"
```

---

## Self-review notes

- **Spec coverage (§5):** push-to-talk ✓ (Task 6), Parakeet STT ✓ (Task 5), Kokoro TTS ✓ (Task 4), sentence-by-sentence spoken output ✓ (Tasks 2+3), `--voice` entry ✓ (Task 7). VAD, streaming-during-hold, wake word, Windows audio explicitly deferred at their seams.
- **Testability:** orchestrator (T3), sentence-splitter (T2), downloader (T4), STT/TTS adapters via injection (T4/T5), and `_run_cycle`/`assemble` (T6) are all hermetic unit tests; the real models are covered by marked integration tests (the recon-proven round-trip); mic+hotkey are the documented live smoke. No unit test loads a model or opens a device.
- **Type/interface consistency:** `SpeechToText.transcribe(audio, sample_rate)`, `TextToSpeech.speak(text)`, `PushToTalk.capture_utterance() -> tuple|None` are used identically across session (T3), adapters (T4–T6), and builder (T7). `VoiceSession(ptt, stt, agent, tts, ...)` positional order matches every construction site.
- **Torch-free:** no task imports torch; STT is MLX, TTS+VAD-if-ever is ONNX.
- **Safety:** voice mode auto-declines Tier-2 CONFIRM tools (documented) rather than shipping a half-built spoken-confirm flow; the sandbox/gate from Plan 2 are unchanged and still enforce.
