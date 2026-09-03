"""Exception types for semantic planning."""


class SemanticPlannerError(Exception):
    """Raised when semantic planning fails.

    Covers: invalid LLM JSON, schema validation failures,
    hallucinated fields, and validation guard rejections.
    """
