"""Exception types for LLM client operations."""


class LLMError(Exception):
    """Base exception for all LLM-related errors."""


class LLMConfigError(LLMError):
    """Raised when LLM configuration is missing or invalid."""


class LLMResponseError(LLMError):
    """Raised when the LLM returns an invalid or unparseable response."""
