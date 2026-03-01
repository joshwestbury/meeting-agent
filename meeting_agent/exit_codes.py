from meeting_agent.errors import (
    CollisionError,
    ConfigError,
    FolderValidationError,
    LinkValidationError,
    MeetingAgentError,
    RetrievalError,
    SchemaValidationError,
    StateError,
)
from meeting_agent.retrieval import AUTH_REQUIRED, NETWORK_ERROR, NOT_FOUND, PARSE_ERROR, RATE_LIMITED


def exit_code_for_error(error: Exception) -> int:
    if isinstance(error, ConfigError):
        return 2
    if isinstance(error, LinkValidationError):
        return 3
    if isinstance(error, FolderValidationError):
        return 4
    if isinstance(error, SchemaValidationError):
        return 5
    if isinstance(error, CollisionError):
        return 6
    if isinstance(error, StateError):
        return 7
    if isinstance(error, RetrievalError):
        if error.code == AUTH_REQUIRED:
            return 20
        if error.code == NOT_FOUND:
            return 21
        if error.code == RATE_LIMITED:
            return 22
        if error.code == NETWORK_ERROR:
            return 23
        if error.code == PARSE_ERROR:
            return 24
        return 25
    if isinstance(error, MeetingAgentError):
        return 30
    return 1


def render_error_message(error: Exception, *, context: str = "Error") -> str:
    tag = _error_tag(error)
    return f"{context} [{tag}]: {error}"


def _error_tag(error: Exception) -> str:
    if isinstance(error, RetrievalError):
        return f"retrieval.{error.code.lower()}"
    if isinstance(error, ConfigError):
        return "config"
    if isinstance(error, LinkValidationError):
        return "link"
    if isinstance(error, FolderValidationError):
        return "folder"
    if isinstance(error, SchemaValidationError):
        return "schema"
    if isinstance(error, CollisionError):
        return "collision"
    if isinstance(error, StateError):
        return "state"
    if isinstance(error, MeetingAgentError):
        return "meeting-agent"
    return "unknown"
