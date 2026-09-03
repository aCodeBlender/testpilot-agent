"""TestIntent — structured representation of a user's test goal.

Produced by the Intent Planner from natural language input.
Consumed by the endpoint selector to filter which endpoints to test.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

_VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


class TestIntent(BaseModel):
    """Structured test intent produced by the LLM Intent Planner.

    Has ``__test__ = False`` to prevent pytest collection.

    Consistency rules enforced by model_validator:
        selection_mode="all"  -> selected_endpoint_ids must be empty
        selection_mode="subset" -> selected_endpoint_ids must be non-empty
        selection_mode="none" -> selected_endpoint_ids must be empty
    """

    __test__ = False

    selection_mode: Literal["all", "subset", "none"]
    selected_endpoint_ids: list[str] = Field(default_factory=list)
    excluded_methods: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_consistency(self) -> "TestIntent":
        """Reject contradictory LLM output."""
        ids = self.selected_endpoint_ids
        mode = self.selection_mode

        if mode == "all" and ids:
            raise ValueError(
                f"selection_mode='all' but selected_endpoint_ids is non-empty: {ids}. "
                f"Use 'subset' mode to select specific endpoints."
            )
        if mode == "subset" and not ids:
            raise ValueError(
                "selection_mode='subset' but selected_endpoint_ids is empty. "
                f"Provide at least one endpoint ID."
            )
        if mode == "none" and ids:
            raise ValueError(
                f"selection_mode='none' but selected_endpoint_ids is non-empty: {ids}. "
                f"'none' means no endpoints match."
            )
        return self

    def model_post_init(self, _context: object) -> None:
        """Normalize after validation."""
        # Uppercase and validate methods
        normalized: list[str] = []
        for m in self.excluded_methods:
            m_upper = m.upper().strip()
            if m_upper not in _VALID_METHODS:
                raise ValueError(f"Invalid HTTP method: {m!r}")
            normalized.append(m_upper)
        self.excluded_methods = normalized

        # Deduplicate endpoint IDs preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for id_ in self.selected_endpoint_ids:
            if id_ not in seen:
                seen.add(id_)
                deduped.append(id_)
        self.selected_endpoint_ids = deduped
