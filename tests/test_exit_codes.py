from meeting_agent.errors import (
    CollisionError,
    ConfigError,
    FolderValidationError,
    LinkValidationError,
    RetrievalError,
    SchemaValidationError,
    StateError,
)
from meeting_agent.exit_codes import exit_code_for_error, render_error_message
from meeting_agent.retrieval import AUTH_REQUIRED, NETWORK_ERROR, NOT_FOUND, PARSE_ERROR, RATE_LIMITED


def test_exit_code_mapping_for_domain_errors() -> None:
    assert exit_code_for_error(ConfigError("bad")) == 2
    assert exit_code_for_error(LinkValidationError("bad")) == 3
    assert exit_code_for_error(FolderValidationError("bad")) == 4
    assert exit_code_for_error(SchemaValidationError("bad")) == 5
    assert exit_code_for_error(CollisionError("bad")) == 6
    assert exit_code_for_error(StateError("bad")) == 7


def test_exit_code_mapping_for_retrieval_codes() -> None:
    assert exit_code_for_error(RetrievalError(AUTH_REQUIRED, "x")) == 20
    assert exit_code_for_error(RetrievalError(NOT_FOUND, "x")) == 21
    assert exit_code_for_error(RetrievalError(RATE_LIMITED, "x")) == 22
    assert exit_code_for_error(RetrievalError(NETWORK_ERROR, "x")) == 23
    assert exit_code_for_error(RetrievalError(PARSE_ERROR, "x")) == 24
    assert exit_code_for_error(RetrievalError("OTHER", "x")) == 25


def test_render_error_message_uses_context_and_tag() -> None:
    msg = render_error_message(RetrievalError(AUTH_REQUIRED, "missing token"), context="Retrieval failed")
    assert msg == "Retrieval failed [retrieval.auth_required]: missing token"
