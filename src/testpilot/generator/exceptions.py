"""Exception types for test case generation."""


class TestCaseGeneratorError(Exception):
    """Raised when test case generation fails."""

    __test__ = False  # prevent pytest from collecting this as a test class
