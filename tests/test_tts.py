from assistant.voice.tts import KokoroTTS


class FakeTokenizer:
    # Deliberately narrow: 'Q' and '#' are NOT in vocab, so a missing vocab
    # filter shows up as those characters reaching create().
    vocab = set("abcdefghijklmnopqrstuvwxyz ˈːɾɪŋæθɹəklɑ.'")


class FakeKokoro:
    """Mirrors the real kokoro_onnx.Kokoro.create signature.

    Keeping `is_phonemes` here matters: the previous fake omitted it, so a
    fast path that passed it would have blown up only against the real
    library, not in tests.
    """

    def __init__(self, with_tokenizer=True):
        self.calls = []
        if with_tokenizer:
            self.tokenizer = FakeTokenizer()

    def create(self, text, voice, speed=1.0, lang="en-us", is_phonemes=False,
               trim=True):
        self.calls.append(
            {"text": text, "voice": voice, "lang": lang, "is_phonemes": is_phonemes}
        )
        return ([0.0, 0.1, 0.0], 24000)


def test_kokoro_tts_speaks_via_injected_kokoro_and_player():
    played = []
    tts = KokoroTTS(
        "af_heart",
        kokoro=FakeKokoro(),
        player=lambda a, sr: played.append((a, sr)),
        phonemizer=lambda text, lang: "hɛloʊ",
    )
    tts.speak("hello")
    assert played and played[0][1] == 24000


def test_uses_phoneme_fast_path_and_marks_is_phonemes():
    """The whole point of the optimization: hand kokoro phonemes, not text.

    Fails on the pre-fix implementation, which always called create() with
    raw text and is_phonemes defaulting to False.
    """
    kokoro = FakeKokoro()
    tts = KokoroTTS(
        "af_heart",
        kokoro=kokoro,
        player=lambda a, sr: None,
        phonemizer=lambda text, lang: "ðə mˈiːɾɪŋ",
    )
    tts.speak("The meeting")

    assert len(kokoro.calls) == 1
    call = kokoro.calls[0]
    assert call["is_phonemes"] is True
    assert call["text"] != "The meeting"  # phonemes, not graphemes
    assert "ɾɪŋ" in call["text"]


def test_phonemes_are_filtered_to_model_vocab():
    """kokoro drops out-of-vocab phonemes before inference; so must we.

    Without the filter the model receives tokens it was never trained on.
    Fails if the `p in vocab` filter is removed.
    """
    kokoro = FakeKokoro()
    tts = KokoroTTS(
        "af_heart",
        kokoro=kokoro,
        player=lambda a, sr: None,
        phonemizer=lambda text, lang: "hɛlQ#oʊ",
    )
    tts.speak("hello")

    text = kokoro.calls[0]["text"]
    assert "Q" not in text and "#" not in text


def test_falls_back_to_kokoro_phonemization_when_fast_path_fails():
    """A broken espeak backend must degrade to slow-but-working, not crash.

    Fails if the try/except around phonemization is removed.
    """

    def boom(text, lang):
        raise RuntimeError("espeak unavailable")

    kokoro = FakeKokoro()
    tts = KokoroTTS(
        "af_heart", kokoro=kokoro, player=lambda a, sr: None, phonemizer=boom
    )
    tts.speak("hello there")

    call = kokoro.calls[0]
    assert call["is_phonemes"] is False
    assert call["text"] == "hello there"  # raw text handed to kokoro


def test_falls_back_when_kokoro_exposes_no_tokenizer():
    """Injected/duck-typed kokoro objects without .tokenizer must still work."""
    kokoro = FakeKokoro(with_tokenizer=False)
    tts = KokoroTTS(
        "af_heart",
        kokoro=kokoro,
        player=lambda a, sr: None,
        phonemizer=lambda text, lang: "hɛloʊ",
    )
    tts.speak("hello")

    assert kokoro.calls[0]["is_phonemes"] is False
    assert kokoro.calls[0]["text"] == "hello"


def test_empty_phonemization_falls_back_rather_than_synthesizing_silence():
    """An all-out-of-vocab result must not be passed through as empty text."""
    kokoro = FakeKokoro()
    tts = KokoroTTS(
        "af_heart",
        kokoro=kokoro,
        player=lambda a, sr: None,
        phonemizer=lambda text, lang: "QQQ###",
    )
    tts.speak("hello")

    assert kokoro.calls[0]["is_phonemes"] is False
    assert kokoro.calls[0]["text"] == "hello"


def test_backend_cache_is_keyed_by_language():
    """The 1.8s saving depends on reuse; a per-call rebuild would undo it."""
    from assistant.voice import tts as tts_mod

    built = []

    class FakeBackend:
        def __init__(self, lang):
            built.append(lang)

        def phonemize(self, texts):
            return ["hɛloʊ"]

    tts_mod._backends.clear()
    try:
        tts_mod._backends["en-us"] = FakeBackend("en-us")
        first = tts_mod._espeak_backend("en-us")
        second = tts_mod._espeak_backend("en-us")
        assert first is second
        assert built == ["en-us"]  # constructed once, not per call
    finally:
        tts_mod._backends.clear()
