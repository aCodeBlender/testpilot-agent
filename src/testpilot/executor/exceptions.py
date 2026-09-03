"""Exception types for request building and execution."""


class RequestBuildError(Exception):
    """Raised when a request cannot be constructed from a TestCase."""


class HttpExecutorError(Exception):
    """Raised when the executor encounters an unsupported configuration."""
