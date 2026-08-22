import importlib
import sys

import pytest

from assistant.voice.interfaces import PushToTalk, SpeechToText, TextToSpeech


def test_interfaces_import_without_numpy(monkeypatch):
    # Verify interfaces.py can be imported with numpy blocked
    # None in sys.modules makes `import numpy` raise ImportError
    monkeypatch.setitem(sys.modules, "numpy", None)
    sys.modules.pop("assistant.voice.interfaces", None)
    mod = importlib.import_module("assistant.voice.interfaces")
    assert hasattr(mod.SpeechToText, "transcribe")
    assert hasattr(mod.TextToSpeech, "speak")
    assert hasattr(mod.PushToTalk, "capture_utterance")
    # monkeypatch auto-restores sys.modules['numpy'] after the test


def test_duck_typed_impl_satisfies_protocol():
    class FakeSTT:
        def transcribe(self, audio, sample_rate):
            return "hi"

    assert isinstance(FakeSTT(), SpeechToText)
