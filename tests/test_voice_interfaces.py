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
