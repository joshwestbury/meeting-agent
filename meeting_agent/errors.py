class MeetingAgentError(Exception):
    """Base error for meeting-agent."""


class ConfigError(MeetingAgentError):
    """Raised when configuration is missing or invalid."""


class RetrievalError(MeetingAgentError):
    """Raised when transcript retrieval fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LinkValidationError(MeetingAgentError):
    """Raised when an input Granola link is invalid."""


class FolderValidationError(MeetingAgentError):
    """Raised when a destination folder is invalid or unsafe."""
