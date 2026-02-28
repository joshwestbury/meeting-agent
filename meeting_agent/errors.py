class MeetingAgentError(Exception):
    """Base error for meeting-agent."""


class LinkValidationError(MeetingAgentError):
    """Raised when an input Granola link is invalid."""


class FolderValidationError(MeetingAgentError):
    """Raised when a destination folder is invalid or unsafe."""
