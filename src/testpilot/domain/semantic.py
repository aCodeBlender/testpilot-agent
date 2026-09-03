"""Semantic Scenario Proposal — Phase 3B.

Represents an LLM-proposed test scenario that goes beyond deterministic
schema rules.  Proposals are NOT executable TestScenario objects — they
require further validation and (in future batches) execution support.

Key separation:
    SemanticScenarioProposal  ≠  TestScenario
    (LLM suggestion)            (executable scenario)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ── Constrained type aliases ────────────────────────────────────────────────

SemanticCategory = Literal[
    "format_violation",
    "boundary",
    "business_rule",
    "duplicate_resource",
    "invalid_state",
    "authorization",
    "relationship",
    "semantic",
]
"""Categories of semantic test scenarios that require domain interpretation."""

SemanticStrategy = Literal[
    "mutate_field",
    "omit_field",
    "reuse_existing_value",
    "custom_value",
    "multi_step_required",
    "analysis_only",
]
"""How the proposal intends to construct the test case."""

SemanticTargetLocation = Literal["path", "query", "header", "cookie", "body", "auth"]
"""Where the mutation target lives in the HTTP request."""


# ── SemanticScenarioProposal ───────────────────────────────────────────────


class SemanticScenarioProposal(BaseModel):
    """An LLM-proposed test scenario.

    These are *suggestions*, not executable test cases.  They must pass
    deterministic validation before they can ever become TestScenario objects.

    ``__test__ = False`` prevents pytest from collecting this domain model.
    """

    __test__ = False

    endpoint_id: str = Field(
        description="ID of the ApiEndpoint this proposal targets",
    )

    name: str = Field(description="Short human-readable name")
    description: str = Field(description="Detailed description of what this tests")
    rationale: str = Field(description="Why this scenario matters")

    category: SemanticCategory = Field(
        description="High-level semantic category",
    )

    target_location: SemanticTargetLocation | None = Field(
        default=None,
        description="Where the mutation target lives (None for analysis_only)",
    )

    target_path: str | None = Field(
        default=None,
        description="Dotted path to the specific field (e.g. 'email', 'profile.email')",
    )

    strategy: SemanticStrategy = Field(
        description="How to construct the test case",
    )

    proposed_value: Any | None = Field(
        default=None,
        description="The proposed value to use (None when strategy does not need one)",
    )

    requires_state: bool = Field(
        default=False,
        description="True when the scenario needs prior API state (e.g. create-then-duplicate)",
    )

    @model_validator(mode="after")
    def _check_stateful_consistency(self) -> "SemanticScenarioProposal":
        """Enforce stateful strategy constraints."""
        if self.strategy == "multi_step_required" and not self.requires_state:
            raise ValueError(
                "strategy='multi_step_required' requires requires_state=True"
            )
        return self
