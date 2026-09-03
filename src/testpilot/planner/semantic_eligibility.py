"""Semantic Execution Eligibility — Phase 3B Batch 2 T0320.

Determines which SemanticScenarioProposals can be converted into executable
TestCase objects.  Only proposals whose invalidity can be proven from explicit
OpenAPI constraints become executable.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from testpilot.domain.schema import ApiSchema
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint
from testpilot.planner.semantic_constraint import ConstraintCheckResult, check_constraint


# ── Decision model ──────────────────────────────────────────────────────────


class SemanticExecutionDecision(BaseModel):
    """Decision for a single proposal."""

    __test__ = False

    proposal: SemanticScenarioProposal
    eligible: bool = Field(description="Whether the proposal is eligible for execution")
    category: Literal["eligible", "not_executable", "blocked"] = Field(
        description="Eligibility category"
    )
    reason: str = Field(description="Human-readable explanation")
    constraint_result: ConstraintCheckResult | None = Field(
        default=None,
        description="Result of constraint check if applicable",
    )
    target_schema: ApiSchema | None = Field(
        default=None,
        description="Schema of the target field if resolved",
    )


# ── Non-executable categories ───────────────────────────────────────────────

_NON_EXECUTABLE_STRATEGIES = frozenset({
    "multi_step_required",
    "analysis_only",
    "omit_field",
    "mutate_field",
    "reuse_existing_value",
})

_NON_EXECUTABLE_TARGET_TYPES = frozenset({"array", "object"})


# ── Public API ──────────────────────────────────────────────────────────────


def analyze_execution_eligibility(
    proposals: list[SemanticScenarioProposal],
    endpoint: ApiEndpoint,
) -> list[SemanticExecutionDecision]:
    """Analyze each proposal and return an eligibility decision.

    Parameters
    ----------
    proposals:
        Validated, deduplicated proposals from the semantic planner.
    endpoint:
        The API endpoint these proposals target.

    Returns
    -------
    list[SemanticExecutionDecision]
    """
    decisions: list[SemanticExecutionDecision] = []

    for proposal in proposals:
        decision = _analyze_single(proposal, endpoint)
        decisions.append(decision)

    return decisions


# ── Internal helpers ────────────────────────────────────────────────────────


def _analyze_single(
    proposal: SemanticScenarioProposal,
    endpoint: ApiEndpoint,
) -> SemanticExecutionDecision:
    """Analyze a single proposal for execution eligibility."""

    # Rule 1: strategy must be custom_value
    if proposal.strategy != "custom_value":
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason=f"strategy '{proposal.strategy}' is not executable",
        )

    # Rule 2: additional strategy guard (defense in depth)
    if proposal.strategy in _NON_EXECUTABLE_STRATEGIES:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason=f"strategy '{proposal.strategy}' is not executable",
        )

    # Rule 3: must not require state
    if proposal.requires_state:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason="requires_state=True proposals are not executable",
        )

    # Rule 4: must have proposed_value
    if proposal.proposed_value is None:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason="no proposed_value",
        )

    # Rule 5: must have target_location
    if proposal.target_location is None:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason="no target_location",
        )

    # Rule 6: must have target_path
    if not proposal.target_path:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason="no target_path",
        )

    # Rule 6b: only body mutations are currently supported
    if proposal.target_location != "body":
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason=f"target_location '{proposal.target_location}' is not supported — only body mutation is implemented",
        )

    # Resolve the target schema
    target_schema = _resolve_target_schema(proposal, endpoint)

    if target_schema is None:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="blocked",
            reason="could not resolve target schema from endpoint",
        )

    # Rule 7: readOnly field
    if target_schema.read_only:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="blocked",
            reason="target field is readOnly",
        )

    # Rule 8: target type must be primitive
    if target_schema.type in _NON_EXECUTABLE_TARGET_TYPES:
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason=f"target type '{target_schema.type}' is not supported for mutation",
        )

    # Rule 9: constraint check — value must violate at least one explicit constraint
    constraint_result = check_constraint(proposal.proposed_value, target_schema)

    # cannot_determine → NOT EXECUTABLE (safety invariant)
    if constraint_result.status == "cannot_determine":
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason=f"cannot determine constraint validity: {constraint_result.detail}",
            constraint_result=constraint_result,
            target_schema=target_schema,
        )

    if constraint_result.status == "valid":
        return SemanticExecutionDecision(
            proposal=proposal,
            eligible=False,
            category="not_executable",
            reason="proposed_value does not violate any explicit schema constraint",
            constraint_result=constraint_result,
            target_schema=target_schema,
        )

    # Eligible!
    return SemanticExecutionDecision(
        proposal=proposal,
        eligible=True,
        category="eligible",
        reason=f"value violates: {', '.join(constraint_result.violated_constraints)}",
        constraint_result=constraint_result,
        target_schema=target_schema,
    )


def _resolve_target_schema(
    proposal: SemanticScenarioProposal,
    endpoint: ApiEndpoint,
) -> ApiSchema | None:
    """Resolve the ApiSchema for the proposal's target field.

    Returns None if the path cannot be resolved.
    """
    location = proposal.target_location
    path = proposal.target_path

    if location == "body":
        return _resolve_body_schema(proposal, endpoint)
    elif location == "query":
        return _resolve_param_schema(endpoint, "query", path)
    elif location == "header":
        return _resolve_param_schema(endpoint, "header", path)
    elif location == "path":
        return _resolve_param_schema(endpoint, "path", path)
    return None


def _resolve_body_schema(
    proposal: SemanticScenarioProposal,
    endpoint: ApiEndpoint,
) -> ApiSchema | None:
    """Resolve schema for a body field path."""
    if endpoint.request_body is None:
        return None

    body_schema = endpoint.request_body.body_schema
    path = proposal.target_path

    if not path:
        return body_schema

    # Walk the path segments through the schema tree
    segments = path.strip(".").split(".")
    current = body_schema

    for segment in segments:
        if current.type == "object" and current.properties and segment in current.properties:
            current = current.properties[segment]
        else:
            return None

    return current


def _resolve_param_schema(
    endpoint: ApiEndpoint,
    location: str,
    param_name: str | None,
) -> ApiSchema | None:
    """Resolve schema for a parameter by name and location."""
    if not param_name:
        return None

    for param in endpoint.parameters:
        if param.location == location and param.name == param_name:
            return param.param_schema

    return None
