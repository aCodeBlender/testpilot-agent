"""Semantic Execution Wiring — Phase 3B Batch 3.

Converts eligible SemanticExecutionDecision objects into executable
TestScenario + TestCase pairs that plug directly into the existing
Runner pipeline (HttpExecutor + Validator).

Only body mutations with explicit constraint violations are wired.
All other proposals are silently skipped.
"""

from __future__ import annotations

from typing import Any

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.testing import TestCase, TestScenario
from testpilot.generator.testcase_generator import _build_base_request
from testpilot.generator.semantic_mutation import mutate_request_for_semantic
from testpilot.planner.semantic_eligibility import SemanticExecutionDecision


# ── ID generation ───────────────────────────────────────────────────────────


def _make_semantic_scenario_id(
    endpoint_id: str,
    target_path: str | None,
    seen: set[str],
) -> str:
    """Generate a unique scenario ID for a semantic proposal.

    Uses ``sem-`` prefix to distinguish from deterministic ``sc-`` IDs.
    """
    suffix = target_path.replace(".", "_") if target_path else "none"
    base = f"sem-{endpoint_id}-{suffix}"
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


# ── Public API ──────────────────────────────────────────────────────────────


def build_semantic_test_cases(
    decision: SemanticExecutionDecision,
    endpoint: ApiEndpoint,
    seen_ids: set[str] | None = None,
) -> list[tuple[TestScenario, TestCase]]:
    """Convert an eligible decision into executable TestScenario + TestCase.

    Parameters
    ----------
    decision:
        An eligible SemanticExecutionDecision (``eligible=True``).
    endpoint:
        The API endpoint this decision targets.
    seen_ids:
        Optional set of already-used scenario IDs (for uniqueness).

    Returns
    -------
    list[tuple[TestScenario, TestCase]]
        Typically one pair.  Empty if the decision cannot be wired
        (e.g. non-body target — defense in depth).
    """
    proposal = decision.proposal

    # Defense in depth: only body mutations are supported
    if proposal.target_location != "body":
        return []

    if seen_ids is None:
        seen_ids = set()

    # Build a valid base request
    base_request = _build_base_request(endpoint)

    # Apply semantic mutation
    mutation_result = mutate_request_for_semantic(
        base_request,
        proposal,
        endpoint,
        constraints_violated=(
            decision.constraint_result.violated_constraints
            if decision.constraint_result
            else []
        ),
    )

    # Build TestScenario
    scenario_id = _make_semantic_scenario_id(
        endpoint.id, proposal.target_path, seen_ids
    )
    seen_ids.add(scenario_id)

    scenario = TestScenario(
        id=scenario_id,
        endpoint_id=endpoint.id,
        source="llm",
        category="semantic_negative",
        name=proposal.name,
        description=proposal.description,
        rationale=proposal.rationale,
        target_location=proposal.target_location,
        target_path=proposal.target_path,
    )

    # Build TestCase from mutated request
    mutated = mutation_result.mutated_request
    case_id = f"tc-{scenario_id}-1"

    case = TestCase(
        id=case_id,
        endpoint_id=endpoint.id,
        scenario_id=scenario_id,
        method=endpoint.method,
        path=endpoint.path,
        headers=mutated.get("headers", {}),
        query_params=mutated.get("query_params", {}),
        path_params=mutated.get("path_params", {}),
        cookies=mutated.get("cookies", {}),
        body=mutated.get("body"),
    )

    return [(scenario, case)]
