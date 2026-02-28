from dataclasses import dataclass
import re
from urllib.parse import urlparse

from meeting_agent.errors import LinkValidationError


_MEETING_TOKEN_RE = re.compile(
    r"^(?P<meeting_uuid>[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12})(?:-[A-Za-z0-9]+)?$"
)


@dataclass(frozen=True)
class ParsedGranolaLink:
    source_url: str
    meeting_id: str
    raw_token: str


def parse_granola_link(source_url: str) -> ParsedGranolaLink:
    """Parse and validate Granola transcript URL."""
    normalized_source_url = source_url.strip()
    parsed = urlparse(normalized_source_url)
    if parsed.scheme != "https":
        raise LinkValidationError("Granola link must use https")
    if parsed.netloc.lower() != "notes.granola.ai":
        raise LinkValidationError("Granola link must use notes.granola.ai")

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 2 or path_parts[0] != "t":
        raise LinkValidationError("Granola link path must be /t/<meeting-token>")

    raw_token = path_parts[1]
    match = _MEETING_TOKEN_RE.fullmatch(raw_token)
    if not match:
        raise LinkValidationError("Granola link token is malformed")

    meeting_id = match.group("meeting_uuid").lower()
    return ParsedGranolaLink(
        source_url=normalized_source_url,
        meeting_id=meeting_id,
        raw_token=raw_token,
    )
