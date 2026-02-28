import pytest

from meeting_agent.errors import SchemaValidationError
from meeting_agent.llm import (
    build_no_llm_payload,
    detect_sensitive,
    generate_note_payload_with_llm,
)


def test_detect_sensitive_true_on_ssn_pattern() -> None:
    assert detect_sensitive("Customer SSN is 123-45-6789") is True


def test_detect_sensitive_respects_force_sensitive() -> None:
    assert detect_sensitive("clean transcript", force_sensitive=True) is True


def test_detect_sensitive_supports_extra_patterns() -> None:
    assert detect_sensitive("contains SECRET_TOKEN", extra_patterns=[r"secret_token"]) is True


def test_detect_sensitive_false_on_clean_text() -> None:
    assert detect_sensitive("project updates and timeline review") is False


def test_detect_sensitive_ignores_invalid_extra_pattern() -> None:
    assert detect_sensitive("clean transcript", extra_patterns=["[invalid"]) is False


def test_build_no_llm_payload_returns_valid_template() -> None:
    note = build_no_llm_payload(
        meeting_date="2026-02-28",
        title="My Meeting",
        folder_choice="Inbox/Meetings/",
        tags=["meeting", "manual"],
    )
    assert note.title == "My Meeting"
    assert note.folder_choice == "Inbox/Meetings/"
    assert "Transcript available in staging." in note.key_details


def test_generate_note_payload_with_llm_accepts_dict_output() -> None:
    def _mock_llm(_: str, __: list[str]):
        return {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "Summary",
            "action_items": [],
            "key_details": ["detail"],
            "sensitive": False,
        }

    note = generate_note_payload_with_llm(
        "text",
        ["Inbox/Meetings/"],
        _mock_llm,
    )
    assert note.folder_choice == "Inbox/Meetings/"


def test_generate_note_payload_with_llm_accepts_json_string_output() -> None:
    def _mock_llm(_: str, __: list[str]):
        return """{
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "Summary",
            "action_items": [],
            "key_details": ["detail"],
            "sensitive": false
        }"""

    note = generate_note_payload_with_llm("text", ["Inbox/Meetings/"], _mock_llm)
    assert note.key_details == ["detail"]


def test_generate_note_payload_with_llm_rejects_invalid_candidate() -> None:
    def _mock_llm(_: str, __: list[str]):
        return {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Work/Meetings/Internal/",
            "summary": "Summary",
            "action_items": [],
            "key_details": [],
            "sensitive": False,
        }

    with pytest.raises(SchemaValidationError):
        generate_note_payload_with_llm("text", ["Inbox/Meetings/"], _mock_llm)


def test_generate_note_payload_with_llm_rejects_empty_candidates() -> None:
    def _mock_llm(_: str, __: list[str]):
        return {}

    with pytest.raises(SchemaValidationError):
        generate_note_payload_with_llm("text", [], _mock_llm)


def test_generate_note_payload_with_llm_enforces_max_total_chars() -> None:
    def _mock_llm(_: str, __: list[str]):
        return {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "x" * 200,
            "action_items": [],
            "key_details": [],
            "sensitive": False,
        }

    with pytest.raises(SchemaValidationError):
        generate_note_payload_with_llm("text", ["Inbox/Meetings/"], _mock_llm, max_total_chars=100)
