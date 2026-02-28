from meeting_agent.normalize import (
    compute_source_key,
    compute_transcript_hash,
    normalize_transcript_text,
)


def test_normalize_transcript_text_normalizes_newlines_and_whitespace() -> None:
    raw = " line one  \r\n\r\n\r\nline two\t \rline three  \n\n"
    normalized = normalize_transcript_text(raw)
    assert normalized == "line one\n\nline two\nline three"


def test_compute_transcript_hash_is_stable() -> None:
    text = "a\nb\nc"
    assert compute_transcript_hash(text) == compute_transcript_hash(text)


def test_compute_source_key_prefers_granola_id() -> None:
    assert compute_source_key("abc-123", "ignored") == "abc-123"


def test_compute_source_key_falls_back_to_hash() -> None:
    text = "sample"
    assert compute_source_key("", text) == compute_transcript_hash(text)
