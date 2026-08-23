"""A live level meter, because "Listening…" is a label, not feedback.

With only a status word, a working microphone and a dead one look identical:
the user speaks, sees nothing change, and reasonably concludes it is not
listening. That happened. The meter makes "it can hear you" observable.
"""
import numpy as np

from assistant.voice.audio import level_bar, rms_level


def test_silence_reads_zero():
    assert rms_level([np.zeros(1000, dtype="float32")]) == 0.0


def test_loud_audio_reads_higher_than_quiet():
    quiet = [np.full(1000, 0.02, dtype="float32")]
    loud = [np.full(1000, 0.5, dtype="float32")]
    assert rms_level(loud) > rms_level(quiet)


def test_level_is_bounded_so_the_meter_cannot_overflow():
    huge = [np.full(1000, 10.0, dtype="float32")]
    assert 0.0 <= rms_level(huge) <= 1.0


def test_no_frames_reads_zero_rather_than_raising():
    assert rms_level([]) == 0.0


def test_only_recent_audio_counts():
    """A meter reflecting the whole recording would freeze after a loud start."""
    frames = [np.full(16000, 0.9, dtype="float32")] + [
        np.zeros(16000, dtype="float32") for _ in range(5)
    ]
    recent = rms_level(frames, window_frames=2)
    whole = rms_level(frames, window_frames=None)
    assert recent < whole, "meter is showing stale audio"


def test_bar_grows_with_level():
    assert len(level_bar(0.0).strip()) <= len(level_bar(0.5).strip()) <= len(
        level_bar(1.0).strip()
    )


def test_bar_is_fixed_width_so_the_window_does_not_jitter():
    assert len(level_bar(0.0)) == len(level_bar(0.5)) == len(level_bar(1.0))


def test_silence_still_renders_something():
    """An empty meter is indistinguishable from a broken one."""
    assert level_bar(0.0).strip() != ""
