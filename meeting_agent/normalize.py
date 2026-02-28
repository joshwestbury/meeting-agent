from hashlib import sha256
import re


_REPEATED_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_transcript_text(text: str) -> str:
    """Normalize transcript text for stable hashing and output consistency."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = _REPEATED_BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def compute_transcript_hash(normalized_text: str) -> str:
    return sha256(normalized_text.encode("utf-8")).hexdigest()


def compute_source_key(granola_id: str | None, normalized_text: str) -> str:
    if granola_id and granola_id.strip():
        return granola_id.strip()
    return compute_transcript_hash(normalized_text)
