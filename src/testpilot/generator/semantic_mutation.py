"""Semantic Mutation Adapter — Phase 3B Batch 2 T0322.

Applies a semantic negative mutation to a valid base request.
Only body properties are mutated; all other valid fields are preserved.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field

from testpilot.domain.schema import ApiSchema
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint


# ── Result model ────────────────────────────────────────────────────────────


class SemanticMutationResult(BaseModel):
    """Result of applying a semantic mutation to a base request."""

    __test__ = False

    mutated_request: dict[str, Any] = Field(
        description="The full mutated request dict (headers, query_params, body, etc.)"
    )
    original_value: Any = Field(
        default=None,
        description="The original value at the target path before mutation"
    )
    mutated_value: Any = Field(
        description="The value that was set at the target path"
    )
    constraints_violated: list[str] = Field(
        default_factory=list,
        description="Names of constraints the mutated value violates"
    )


# ── Public API ──────────────────────────────────────────────────────────────


def mutate_request_for_semantic(
    base_request: dict[str, Any],
    proposal: SemanticScenarioProposal,
    endpoint: ApiEndpoint,
    constraints_violated: list[str] | None = None,
) -> SemanticMutationResult:
    """Apply a semantic negative mutation to a base request.

    Only mutates body properties at the specified target_path.
    All other valid fields are preserved.

    Parameters
    ----------
    base_request:
        The valid base request dict (from _build_base_request).
    proposal:
        The semantic scenario proposal with mutation details.
    endpoint:
        The API endpoint (for context).
    constraints_violated:
        Pre-computed list of violated constraint names.

    Returns
    -------
    SemanticMutationResult
    """
    # Deep copy to avoid mutating the original
    mutated = copy.deepcopy(base_request)
    body = mutated.get("body")

    # Capture original value
    original_value = None
    if body is not None and proposal.target_path:
        original_value = _get_nested(body, proposal.target_path)

    # Apply mutation
    if body is not None and proposal.target_path:
        _set_nested(body, proposal.target_path, proposal.proposed_value)
    elif body is None and proposal.target_location == "body":
        # If there's no body but the proposal targets body, create a minimal one
        if proposal.target_path:
            body = {}
            _set_nested(body, proposal.target_path, proposal.proposed_value)
            mutated["body"] = body

    return SemanticMutationResult(
        mutated_request=mutated,
        original_value=original_value,
        mutated_value=proposal.proposed_value,
        constraints_violated=constraints_violated or [],
    )


# ── Nested dict helpers ─────────────────────────────────────────────────────


def _get_nested(obj: Any, dotted_path: str) -> Any:
    """Get a value from a nested dict by dotted path.

    >>> _get_nested({"a": {"b": 1}}, "a.b")
    1
    """
    segments = dotted_path.split(".")
    current = obj
    for segment in segments:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current


def _set_nested(obj: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict by dotted path.

    Creates intermediate dicts as needed.
    >>> d = {"a": {"b": 1}}
    >>> _set_nested(d, "a.b", 2)
    >>> d
    {'a': {'b': 2}}
    """
    segments = dotted_path.split(".")
    current = obj
    for segment in segments[:-1]:
        if segment not in current or not isinstance(current[segment], dict):
            current[segment] = {}
        current = current[segment]
    current[segments[-1]] = value
