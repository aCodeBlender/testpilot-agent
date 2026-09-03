"""Deterministic validation and deduplication for semantic proposals — T0312.

All LLM proposals must be deterministically checked before use.
This module validates SemanticScenarioProposal objects against
ApiEndpoint metadata and deduplicates them.

These functions operate on already-parsed SemanticScenarioProposal objects.
For raw dict validation during LLM response parsing, see semantic_planner.py.
"""

from __future__ import annotations

import json
from typing import Any

from testpilot.domain.schema import ApiSchema, ApiParameter
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint
from testpilot.planner.semantic_exceptions import SemanticPlannerError


# ── Public API ──────────────────────────────────────────────────────────────


def validate_proposals(
    proposals: list[SemanticScenarioProposal],
    endpoint: ApiEndpoint,
) -> list[SemanticScenarioProposal]:
    """Validate proposals against endpoint metadata.

    Checks:
    1. endpoint_id must match
    2. target_path must refer to a real request-side field
    3. target_location must match actual field location
    4. readOnly fields must not be mutation targets
    5. multi_step_required must have requires_state=True
    6. reuse_existing_value must have requires_state=True
    7. No invented paths/fields
    8. analysis_only skips field validation (observational, not mutation)

    Raises SemanticPlannerError on any violation.
    """
    validated: list[SemanticScenarioProposal] = []
    errors: list[str] = []

    for i, proposal in enumerate(proposals):
        # 1. endpoint_id must match
        if proposal.endpoint_id != endpoint.id:
            errors.append(
                f"Proposal {i} ({proposal.name!r}): "
                f"endpoint_id '{proposal.endpoint_id}' does not match "
                f"endpoint '{endpoint.id}'"
            )
            continue

        # 8. analysis_only skips field path validation
        if proposal.strategy == "analysis_only":
            # Still validate the field exists if target_path is given
            if proposal.target_path is not None:
                try:
                    _validate_target_path(proposal, endpoint)
                except SemanticPlannerError as exc:
                    errors.append(f"Proposal {i} ({proposal.name!r}): {exc}")
                    continue
            validated.append(proposal)
            continue

        # 2-4. target_path and target_location validation
        if proposal.target_path is not None:
            try:
                _validate_target_path(proposal, endpoint)
            except SemanticPlannerError as exc:
                errors.append(f"Proposal {i} ({proposal.name!r}): {exc}")
                continue

        # 5. multi_step_required must have requires_state=True
        if proposal.strategy == "multi_step_required" and not proposal.requires_state:
            errors.append(
                f"Proposal {i} ({proposal.name!r}): "
                f"strategy='multi_step_required' requires requires_state=True"
            )
            continue

        # 6. reuse_existing_value must have requires_state=True
        if proposal.strategy == "reuse_existing_value" and not proposal.requires_state:
            errors.append(
                f"Proposal {i} ({proposal.name!r}): "
                f"strategy='reuse_existing_value' requires requires_state=True"
            )
            continue

        validated.append(proposal)

    if errors and not validated:
        raise SemanticPlannerError(
            f"All {len(proposals)} proposals failed validation:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return validated


def _validate_target_path(
    proposal: SemanticScenarioProposal,
    endpoint: ApiEndpoint,
) -> dict[str, Any]:
    """Validate that proposal.target_path refers to a real request-side field.

    Checks location match and readOnly. Returns field info dict.
    Raises SemanticPlannerError on any violation.
    """
    target_path = proposal.target_path
    target_location = proposal.target_location
    assert target_path is not None

    # Body paths
    if target_location == "body" or target_path.startswith("body."):
        return _validate_body_path(target_path, endpoint)

    # Parameter paths
    return _validate_param_path(target_path, target_location, endpoint)


def _validate_body_path(
    target_path: str,
    endpoint: ApiEndpoint,
) -> dict[str, Any]:
    """Validate a body target_path against the endpoint's request body schema.

    Rejects targets that are readOnly OR that live inside a readOnly ancestor.
    """
    if endpoint.request_body is None:
        raise SemanticPlannerError(
            f"target_path '{target_path}' does not match any body field: "
            f"endpoint has no request body"
        )

    # Strip "body." prefix
    if target_path.startswith("body."):
        relative_path = target_path[5:]
    else:
        relative_path = target_path

    # Walk the schema to validate path existence
    schema = endpoint.request_body.body_schema
    parts = relative_path.split(".")

    current_schema = schema
    for j, part in enumerate(parts):
        if current_schema.type != "object" or not current_schema.properties:
            parent = ".".join(parts[:j]) or "root"
            raise SemanticPlannerError(
                f"target_path '{target_path}' does not match any body field: "
                f"cannot traverse into non-object field at '{parent}'"
            )
        if part not in current_schema.properties:
            raise SemanticPlannerError(
                f"target_path '{target_path}' references unknown field '{part}'"
            )
        current_schema = current_schema.properties[part]

    # Check readOnly on the leaf itself
    if current_schema.read_only:
        raise SemanticPlannerError(
            f"target_path '{target_path}' refers to a readOnly field"
        )

    # Ancestor readOnly check: if any ancestor (not the leaf) is readOnly,
    # the leaf is non-writable.
    current_schema = schema
    for j, part in enumerate(parts):
        if current_schema.type != "object" or not current_schema.properties:
            break
        if part not in current_schema.properties:
            break
        prop_schema = current_schema.properties[part]
        # Only check ancestors (not the final leaf)
        if j < len(parts) - 1 and prop_schema.read_only:
            ancestor_path = ".".join(parts[: j + 1])
            raise SemanticPlannerError(
                f"target_path '{target_path}' is inside readOnly ancestor "
                f"'{ancestor_path}' and cannot be a mutation target"
            )
        current_schema = prop_schema

    return {"location": "body", "read_only": False}


def _validate_param_path(
    target_path: str,
    target_location: str | None,
    endpoint: ApiEndpoint,
) -> dict[str, Any]:
    """Validate a parameter target_path against the endpoint's parameters."""
    # Find matching parameter
    for param in endpoint.parameters:
        if param.name == target_path:
            # Location check
            if target_location is not None and param.location != target_location:
                raise SemanticPlannerError(
                    f"target_path '{target_path}' does not match any "
                    f"{target_location} parameter (actual: {param.location})"
                )
            return {"location": param.location, "read_only": False}

    # Not found
    if target_location:
        valid_names = [p.name for p in endpoint.parameters if p.location == target_location]
        raise SemanticPlannerError(
            f"target_path '{target_path}' does not match any {target_location} "
            f"parameter. Valid: {valid_names}"
        )
    raise SemanticPlannerError(
        f"target_path '{target_path}' does not refer to a real request-side field"
    )


def deduplicate_proposals(
    proposals: list[SemanticScenarioProposal],
) -> list[SemanticScenarioProposal]:
    """Remove genuinely identical proposals, preserving order.

    The dedup key is the canonical JSON representation of the entire
    proposal — all fields including name, description, rationale.
    This ensures semantically distinct proposals (e.g. "cancel an
    already-cancelled order" vs "cancel an already-shipped order")
    are never merged.

    ``model_dump(mode="json")`` preserves JSON types (int 1 ≠ str "1").
    """
    seen: set[str] = set()
    result: list[SemanticScenarioProposal] = []

    for proposal in proposals:
        key = _dedup_key(proposal)
        if key not in seen:
            seen.add(key)
            result.append(proposal)

    return result


# ── Internal helpers ────────────────────────────────────────────────────────


def _dedup_key(proposal: SemanticScenarioProposal) -> str:
    """Build a canonical dedup key from the entire proposal.

    Uses ``model_dump(mode="json")`` so that JSON type distinctions
    are preserved (e.g. int 1 vs string "1").
    """
    return json.dumps(
        proposal.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
