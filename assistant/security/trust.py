from __future__ import annotations


class SessionTrust:
    """Tracks whether untrusted content has entered this session.

    Rule of Two: an agent that has ingested untrusted content AND can act
    outbound must not do so unsupervised. Once untrusted content is seen,
    outbound tools are elevated to require explicit confirmation.
    """

    def __init__(self) -> None:
        self._sources: list[str] = []

    def note_untrusted_ingest(self, source: str) -> None:
        if source not in self._sources:
            self._sources.append(source)

    def has_ingested_untrusted(self) -> bool:
        return bool(self._sources)

    def sources(self) -> tuple[str, ...]:
        return tuple(self._sources)
