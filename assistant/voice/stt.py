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
        import os
        import soundfile

        fd, path = tempfile.mkstemp(suffix=".wav", prefix="glimmer-stt-")
        os.close(fd)  # mkstemp hands back an open fd; close it, we only need the path
        tmp = Path(path)
        try:
            soundfile.write(str(tmp), audio, sample_rate)
            result = self._model.transcribe(str(tmp))
        finally:
            tmp.unlink(missing_ok=True)
        text = getattr(result, "text", str(result))
        return text.strip()
