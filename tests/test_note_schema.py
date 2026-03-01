import pytest

from meeting_agent.errors import SchemaValidationError
from meeting_agent.note_schema import (
    NotePayload,
    ensure_folder_choice_candidate,
    parse_llm_note_payload,
    validate_note_length,
)


def test_parse_llm_note_payload_accepts_valid_json_dict() -> None:
    payload = {
        "title": "Weekly Sync",
        "meeting_date": "2026-02-28",
        "attendees": ["Alex", "Jamie"],
        "client": "Acme",
        "project": "Pilot",
        "tags": ["meeting", "client"],
        "folder_choice": "Work/Meetings/Clients/Acme/",
        "summary": "Key progress updates and blockers.",
        "action_items": ["Send proposal"],
        "key_details": ["Budget discussed"],
        "decisions": ["Proceed with phase 2"],
        "open_questions": ["Timeline risk"],
        "sensitive": False,
    }
    note = parse_llm_note_payload(payload)
    assert isinstance(note, NotePayload)
    assert note.title == "Weekly Sync"


def test_parse_llm_note_payload_accepts_valid_json_string() -> None:
    note = parse_llm_note_payload(
        """{
        "title": "Weekly Sync",
        "meeting_date": "2026-02-28",
        "attendees": [" Alex ", "  ", "Jamie"],
        "client": " Acme ",
        "project": " Pilot ",
        "tags": [" meeting ", ""],
        "folder_choice": " Inbox/Meetings/ ",
        "summary": " Summary text ",
        "action_items": [" one ", " "],
        "key_details": [" detail "],
        "decisions": [" decision "],
        "open_questions": [" question "],
        "sensitive": false
    }"""
    )
    assert note.attendees == ["Alex", "Jamie"]
    assert note.client == "Acme"
    assert note.project == "Pilot"
    assert note.tags == ["meeting"]
    assert note.folder_choice == "Inbox/Meetings/"
    assert note.summary == "Summary text"
    assert note.action_items == ["one"]
    assert note.key_details == ["detail"]
    assert note.decisions == ["decision"]
    assert note.open_questions == ["question"]


def test_parse_llm_note_payload_rejects_invalid_json_string() -> None:
    invalid = "{bad-json"
    with pytest.raises(SchemaValidationError):
        parse_llm_note_payload(invalid)


def test_parse_llm_note_payload_rejects_unknown_fields() -> None:
    payload = {
        "title": "Weekly Sync",
        "meeting_date": "2026-02-28",
        "attendees": [],
        "client": "",
        "project": "",
        "tags": ["meeting"],
        "folder_choice": "Inbox/Meetings/",
        "summary": "Summary",
        "action_items": [],
        "key_details": [],
        "sensitive": False,
        "unexpected": "nope",
    }
    with pytest.raises(SchemaValidationError):
        parse_llm_note_payload(payload)


def test_ensure_folder_choice_candidate_rejects_non_candidate() -> None:
    note = parse_llm_note_payload(
        {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "Summary",
            "action_items": [],
            "key_details": [],
            "sensitive": False,
        }
    )
    with pytest.raises(SchemaValidationError):
        ensure_folder_choice_candidate(note, ["Work/Meetings/Internal/"])


def test_validate_note_length_rejects_large_payload() -> None:
    note = parse_llm_note_payload(
        {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "a" * 200,
            "action_items": [],
            "key_details": [],
            "sensitive": False,
        }
    )
    with pytest.raises(SchemaValidationError):
        validate_note_length(note, max_total_chars=100)


def test_validate_note_length_accepts_under_limit() -> None:
    note = parse_llm_note_payload(
        {
            "title": "Sync",
            "meeting_date": "2026-02-28",
            "attendees": [],
            "client": "",
            "project": "",
            "tags": ["meeting"],
            "folder_choice": "Inbox/Meetings/",
            "summary": "small",
            "action_items": ["a"],
            "key_details": ["b"],
            "sensitive": False,
        }
    )
    validate_note_length(note, max_total_chars=100)


def test_parse_llm_note_payload_rejects_bad_date_format() -> None:
    payload = {
        "title": "Weekly Sync",
        "meeting_date": "02-28-2026",
        "attendees": [],
        "client": "",
        "project": "",
        "tags": ["meeting"],
        "folder_choice": "Inbox/Meetings/",
        "summary": "Summary",
        "action_items": [],
        "key_details": [],
        "sensitive": False,
    }
    with pytest.raises(SchemaValidationError):
        parse_llm_note_payload(payload)


def test_parse_llm_note_payload_coerces_common_model_shape_drift() -> None:
    note = parse_llm_note_payload(
        {
            "title": "Weekly Sync",
            "meeting_date": "2026-02-28",
            "attendees": "Alex",
            "client": "",
            "project": "",
            "tags": {"topic": "meeting"},
            "folder_choice": "Inbox/Meetings/",
            "summary": "Summary",
            "action_items": {"next_step": "Send pricing"},
            "key_details": {"provisioning_stages": "at order product level"},
            "decisions": None,
            "open_questions": None,
            "sensitive": ["The discussion included integration architecture"],
        }
    )
    assert note.attendees == ["Alex"]
    assert note.tags == ["topic: meeting"]
    assert note.action_items == ["next_step: Send pricing"]
    assert note.key_details == ["provisioning_stages: at order product level"]
    assert note.sensitive is False
