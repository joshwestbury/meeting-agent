import httpx
import pytest

from meeting_agent.errors import SchemaValidationError
from meeting_agent.llm import (
    build_no_llm_payload,
    call_local_llama_server,
    choose_candidate_folder_with_local_runtime,
    generate_note_payload_with_local_runtime,
    generate_note_payload_with_llm,
)


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


def test_call_local_llama_server_extracts_json_from_chat_completion() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"Sync","meeting_date":"2026-02-28","attendees":[],"client":"","project":"","tags":["meeting"],"folder_choice":"Inbox/Meetings/","summary":"Summary","action_items":[],"key_details":[],"sensitive":false}'
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw = call_local_llama_server(
        "transcript",
        ["Inbox/Meetings/"],
        model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        server_url="http://127.0.0.1:8080",
        client=client,
    )
    assert raw.startswith("{")
    client.close()


def test_call_local_llama_server_rejects_http_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaValidationError, match="HTTP 500"):
        call_local_llama_server(
            "transcript",
            ["Inbox/Meetings/"],
            model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
            server_url="http://127.0.0.1:8080",
            client=client,
        )
    client.close()


def test_call_local_llama_server_rejects_malformed_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaValidationError, match="missing choices"):
        call_local_llama_server(
            "transcript",
            ["Inbox/Meetings/"],
            model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
            server_url="http://127.0.0.1:8080",
            client=client,
        )
    client.close()


def test_generate_note_payload_with_local_runtime_success() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": """```json
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
                                "key_details": ["detail"],
                                "sensitive": false
                            }
                            ```"""
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    note = generate_note_payload_with_local_runtime(
        "transcript",
        ["Inbox/Meetings/"],
        model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        server_url="http://127.0.0.1:8080",
        client=client,
    )
    assert note.folder_choice == "Inbox/Meetings/"
    assert note.key_details == ["detail"]
    client.close()


def test_generate_note_payload_with_local_runtime_coerces_wrong_folder() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"Sync","meeting_date":"2026-02-28","attendees":[],"client":"","project":"","tags":["meeting"],"folder_choice":"Work/Meetings/Internal/","summary":"Summary","action_items":[],"key_details":[],"sensitive":false}'
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    note = generate_note_payload_with_local_runtime(
        "transcript",
        ["Inbox/Meetings/"],
        model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        server_url="http://127.0.0.1:8080",
        client=client,
    )
    assert note.folder_choice == "Inbox/Meetings/"
    assert note.summary == "Summary"
    client.close()


def test_generate_note_payload_with_local_runtime_coerces_bad_meeting_date() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"Sync","meeting_date":"Happy Friday","attendees":[],"client":"","project":"","tags":["meeting"],"folder_choice":"Inbox/Meetings/","summary":"Summary","action_items":[],"key_details":[],"sensitive":false}'
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    note = generate_note_payload_with_local_runtime(
        "transcript",
        ["Inbox/Meetings/"],
        model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        server_url="http://127.0.0.1:8080",
        client=client,
    )
    assert note.meeting_date
    assert len(note.meeting_date) == 10
    assert note.summary == "Summary"
    client.close()


def test_choose_candidate_folder_with_local_runtime_selects_index() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "2"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    selected = choose_candidate_folder_with_local_runtime(
        "alter mentis inbox",
        ["Inbox/Meetings/", "Alter Mentis/Inbox/"],
        model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
        server_url="http://127.0.0.1:8080",
        client=client,
    )
    assert selected == "Alter Mentis/Inbox/"
    client.close()


def test_choose_candidate_folder_with_local_runtime_rejects_bad_index() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "99"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SchemaValidationError, match="out of range"):
        choose_candidate_folder_with_local_runtime(
            "alter mentis inbox",
            ["Inbox/Meetings/", "Alter Mentis/Inbox/"],
            model="LiquidAI/LFM2-2.6B-Transcript-GGUF",
            server_url="http://127.0.0.1:8080",
            client=client,
        )
    client.close()
