"""Surface each turn visibly, because audio is the only channel today.

The packaged app has no window and no Dock icon. If you miss the spoken reply
it is gone -- no transcript, no scrollback, no replay. And nothing indicates
the app heard you, is thinking, or is even running.

Notification Centre keeps history, so a missed answer becomes recoverable
without building any UI.
"""
from assistant.voice.notify import Notifier, notification_for


def test_transcription_produces_a_notification_so_you_know_it_heard_you():
    title, body = notification_for("transcribed", "what is on my desktop")
    assert title
    assert "what is on my desktop" in body


def test_answer_produces_a_notification_so_a_missed_reply_is_recoverable():
    title, body = notification_for("answered", "You have three files.")
    assert "You have three files." in body


def test_errors_are_surfaced_not_just_logged():
    title, body = notification_for("error", RuntimeError("mic died"))
    assert "mic died" in body
    assert any(w in title.lower() for w in ("error", "problem", "failed"))


def test_listening_is_not_notified():
    """One notification per key press would be unusable noise."""
    assert notification_for("listening", None) is None


def test_unknown_events_are_ignored_rather_than_crashing_the_turn():
    assert notification_for("something_new", "x") is None


def test_long_bodies_are_trimmed_for_the_notification_panel():
    long = "word " * 400
    _, body = notification_for("answered", long)
    assert len(body) < len(long)


def test_notifier_sends_through_the_injected_backend():
    sent = []
    Notifier(send=lambda t, b: sent.append((t, b))).notify("answered", "hello")
    assert sent and sent[0][1].endswith("hello")


def test_notifier_never_lets_a_failure_break_the_turn():
    """A notification is a nicety; a failed one must not kill a voice session."""

    def boom(title, body):
        raise OSError("notification centre unavailable")

    Notifier(send=boom).notify("answered", "hello")  # must not raise


def test_notifier_skips_events_with_nothing_to_show():
    sent = []
    Notifier(send=lambda t, b: sent.append((t, b))).notify("listening", None)
    assert sent == []
