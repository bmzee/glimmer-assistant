def test_kokoro_tts_speaks_via_injected_kokoro_and_player():
    from assistant.voice.tts import KokoroTTS

    class FakeKokoro:
        def create(self, text, voice, speed, lang):
            return ([0.0, 0.1, 0.0], 24000)

    played = []
    tts = KokoroTTS("af_heart", kokoro=FakeKokoro(), player=lambda a, sr: played.append((a, sr)))
    tts.speak("hello")
    assert played and played[0][1] == 24000
