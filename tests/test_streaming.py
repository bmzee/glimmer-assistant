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
