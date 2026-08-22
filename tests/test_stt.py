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
