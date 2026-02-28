import uuid

import pytest
from hypothesis import given, strategies as st

from meeting_agent.errors import LinkValidationError
from meeting_agent.links import parse_granola_link


_suffix_strategy = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.characters(
            min_codepoint=48,
            max_codepoint=122,
            whitelist_categories=("Ll", "Lu", "Nd"),
        ),
        min_size=1,
        max_size=12,
    ).filter(str.isalnum),
)


@given(meeting_uuid=st.uuids(), suffix=_suffix_strategy)
def test_parse_valid_granola_link_property(meeting_uuid: uuid.UUID, suffix: str) -> None:
    token = f"{meeting_uuid}-{suffix}" if suffix else str(meeting_uuid)
    url = f"https://notes.granola.ai/t/{token}?foo=bar#frag"

    parsed = parse_granola_link(url)

    assert parsed.meeting_id == str(meeting_uuid).lower()
    assert parsed.raw_token == token
    assert parsed.source_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://notes.granola.ai/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        "https://example.com/t/29250e01-0751-4e02-9b24-f6d06f878b04",
        "https://notes.granola.ai/x/29250e01-0751-4e02-9b24-f6d06f878b04",
        "https://notes.granola.ai/t/not-a-uuid",
    ],
)
def test_parse_invalid_granola_link_examples(url: str) -> None:
    with pytest.raises(LinkValidationError):
        parse_granola_link(url)
