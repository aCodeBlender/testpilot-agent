"""Exception types for intent planning."""


class IntentPlannerError(Exception):
    """Raised when intent planning fails (invalid LLM output, hallucinated IDs, etc.)."""
