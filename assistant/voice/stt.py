from __future__ import annotations


def to_model_rate(audio, sample_rate: int, target_rate: int):
    """Resample to the rate the model was trained at.

    ffmpeg was doing two jobs here, not one: decoding the WAV *and* resampling
    it. Live capture asks CoreAudio for 16kHz so it usually needs nothing, but
    TTS output is 24kHz and another input device may deliver its own rate --
    dropping this along with the subprocess would trade a packaging bug for an
    audio one.

    soxr, not librosa.resample. librosa is already in the tree as a
    parakeet_mlx dependency so it looks free, but calling resample lazily
    imports numba, llvmlite, scipy, pooch and joblib -- and PyInstaller does
    not follow lazy imports, so the bundle would build clean and then fail at
    runtime, in an app with no terminal to show why. soxr is what librosa uses
    underneath anyway.
    """
    if int(sample_rate) == int(target_rate):
        return audio
    import soxr

    return soxr.resample(audio, int(sample_rate), int(target_rate))


class ParakeetSTT:
    """Transcribe from the in-memory array, never through a file.

    The previous implementation wrote a temp WAV and handed the path to
    parakeet_mlx's transcribe(), which decodes it by shelling out to ffmpeg
    (parakeet_mlx/audio.py: `if shutil.which("ffmpeg") is None: raise`).

    That is fatal in a packaged .app. A GUI-launched process inherits launchd's
    PATH -- /usr/bin:/bin:/usr/sbin:/sbin -- and Homebrew's /opt/homebrew/bin is
    not on it, so ffmpeg is invisible. Reproduced: the model loads, then every
    transcribe raises RuntimeError, the session catches it, and the user hears
    "Sorry, something went wrong." on every single turn with nothing to
    diagnose from. ffmpeg was declared nowhere -- not in pyproject.toml, not
    bundled, not checked by preflight.

    The round-trip was never needed: the capture path already holds float32
    samples at the model's own rate, and transcribe() itself only calls
    get_logmel() + generate() once ffmpeg has decoded the file back into
    exactly that. So do those two directly.
    """

    def __init__(self, model_id: str, *, model=None):
        if model is None:
            import parakeet_mlx

            model = parakeet_mlx.from_pretrained(model_id)
        self._model = model

    def transcribe(self, audio, sample_rate: int) -> str:
        import mlx.core as mx
        import numpy as np
        from parakeet_mlx.audio import get_logmel

        expected = int(self._model.preprocessor_config.sample_rate)
        samples = np.asarray(audio, dtype="float32").reshape(-1)
        samples = np.asarray(
            to_model_rate(samples, sample_rate, expected), dtype="float32"
        )
        mel = get_logmel(mx.array(samples), self._model.preprocessor_config)
        results = self._model.generate(mel)
        if not results:
            return ""
        text = getattr(results[0], "text", str(results[0]))
        return text.strip()
