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


def test_transcribe_does_not_leak_file_descriptors():
    import os
    from assistant.voice.stt import ParakeetSTT

    class FakeResult:
        text = "hi"

    class FakeModel:
        def transcribe(self, path):
            return FakeResult()

    def open_fd_count():
        # /dev/fd lists this process's open fds on macOS and Linux
        return len(os.listdir("/dev/fd"))

    stt = ParakeetSTT("m", model=FakeModel())
    # warm up one call so any one-time fds are already open
    stt.transcribe(np.zeros(1600, dtype="float32"), 16000)
    before = open_fd_count()
    for _ in range(50):
        stt.transcribe(np.zeros(1600, dtype="float32"), 16000)
    after = open_fd_count()
    assert after <= before, f"leaked {after - before} fds across 50 transcribes"
