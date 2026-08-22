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


def test_download_is_atomic(tmp_path, monkeypatch):
    dest = tmp_path / "kokoro-v1.0.onnx"

    def fake_urlretrieve(url, tmp_path_arg):
        Path(tmp_path_arg).write_bytes(b"model-bytes")

    monkeypatch.setattr(models.urllib.request, "urlretrieve", fake_urlretrieve)

    models._download("http://example.com/kokoro-v1.0.onnx", dest)

    assert dest.exists()
    assert dest.read_bytes() == b"model-bytes"
    assert not dest.with_suffix(dest.suffix + ".part").exists()
