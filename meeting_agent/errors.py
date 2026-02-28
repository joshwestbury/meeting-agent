class MeetingAgentError(Exception):
    """Base error for meeting-agent."""


class ConfigError(MeetingAgentError):
    """Raised when configuration is missing or invalid."""


class LinkValidationError(MeetingAgentError):
    """Raised when an input Granola link is invalid."""


class FolderValidationError(MeetingAgentError):
    """Raised when a destination folder is invalid or unsafe."""
