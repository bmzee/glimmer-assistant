from assistant.security.trust import SessionTrust


def test_starts_clean():
    t = SessionTrust()
    assert t.has_ingested_untrusted() is False
    assert t.sources() == ()


def test_records_ingest():
    t = SessionTrust()
    t.note_untrusted_ingest("read_webpage")
    assert t.has_ingested_untrusted() is True
    assert "read_webpage" in t.sources()


def test_sources_deduplicated_and_ordered():
    t = SessionTrust()
    t.note_untrusted_ingest("a")
    t.note_untrusted_ingest("b")
    t.note_untrusted_ingest("a")
    assert t.sources() == ("a", "b")
