from assistant.voice.streaming import split_sentences


def test_splits_multiple_sentences():
    assert split_sentences("Hello there. How are you? I am fine!") == [
        "Hello there.",
        "How are you?",
        "I am fine!",
    ]


def test_single_sentence_no_terminator():
    assert split_sentences("just one clause") == ["just one clause"]


def test_empty_and_whitespace():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_collapses_internal_whitespace_runs_but_keeps_sentences():
    assert split_sentences("A.\n\nB.") == ["A.", "B."]


# --- SentenceAccumulator: incremental splitting for streamed TTS ---------------
#
# split_sentences() needs the whole answer up front, which is exactly the 2.5s
# gate problem (docs/latency.md): nothing is spoken until generation finishes.
# The accumulator takes token deltas and releases each sentence the moment it
# is complete, so TTS starts on sentence 1 while the model is still writing.

from assistant.voice.streaming import SentenceAccumulator


def test_holds_text_until_a_sentence_terminator_arrives():
    acc = SentenceAccumulator()
    assert acc.feed("Hello") == []
    assert acc.feed(" there") == []
    assert acc.feed(".") == ["Hello there."]


def test_releases_each_sentence_as_it_completes():
    acc = SentenceAccumulator()
    assert acc.feed("One. Two.") == ["One.", "Two."]


def test_deltas_may_split_mid_word():
    """Real token streams break words apart; sentences must survive that."""
    acc = SentenceAccumulator()
    out = []
    for delta in ["The mee", "ting is at th", "ree o'clock", ". See you"]:
        out.extend(acc.feed(delta))
    assert out == ["The meeting is at three o'clock."]


def test_flush_returns_trailing_text_without_a_terminator():
    acc = SentenceAccumulator()
    acc.feed("no terminator here")
    assert acc.flush() == ["no terminator here"]


def test_flush_is_empty_once_everything_was_released():
    acc = SentenceAccumulator()
    acc.feed("Done.")
    assert acc.flush() == []


def test_short_fragments_are_held_back_until_long_enough():
    """Speaking "Dr." as its own utterance sounds broken.

    The splitter treats any '.' as a terminator, so streamed abbreviations
    would each become a standalone TTS call. min_chars coalesces them.
    """
    acc = SentenceAccumulator(min_chars=12)
    assert acc.feed("Dr. ") == []
    assert acc.feed("Smith replied.") == ["Dr. Smith replied."]


def test_min_chars_fragment_is_still_emitted_on_flush():
    acc = SentenceAccumulator(min_chars=12)
    acc.feed("Hi.")
    assert acc.flush() == ["Hi."]


def test_accumulated_text_records_the_full_answer():
    """The session still needs the whole reply for logging and events."""
    acc = SentenceAccumulator()
    acc.feed("One. ")
    acc.feed("Two.")
    acc.flush()
    assert acc.text() == "One. Two."
