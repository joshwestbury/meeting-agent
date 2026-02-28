import pytest

from meeting_agent.errors import LinkValidationError
from meeting_agent.links import parse_granola_link


def test_parse_granola_link_valid_with_suffix_and_query_fragment() -> None:
    url = "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04-00b881l8?x=1#frag"

    parsed = parse_granola_link(url)

    assert parsed.source_url == url
    assert parsed.meeting_id == "29250e01-0751-4e02-9b24-f6d06f878b04"
    assert parsed.raw_token == "29250e01-0751-4e02-9b24-f6d06f878b04-00b881l8"


def test_parse_granola_link_trims_input_whitespace() -> None:
    url = "  https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04  "

    parsed = parse_granola_link(url)

    assert parsed.source_url == "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04"


@pytest.mark.parametrize(
    "url",
    [
        "https://notes.granola.ai/t/",
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04/extra",
        "https://notes.granola.ai/u/29250e01-0751-4e02-9b24-f6d06f878b04",
    ],
)
def test_parse_granola_link_rejects_invalid_path_shapes(url: str) -> None:
    with pytest.raises(LinkValidationError, match="path"):
        parse_granola_link(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b0",  # short
        "https://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b044",  # long
        "https://notes.granola.ai/t/zzzzzzzz-0751-4e02-9b24-f6d06f878b04",  # bad hex
        "https://notes.granola.ai/t/29250e0107514e029b24f6d06f878b04",  # missing dashes
    ],
)
def test_parse_granola_link_rejects_malformed_uuid(url: str) -> None:
    with pytest.raises(LinkValidationError, match="token is malformed"):
        parse_granola_link(url)
