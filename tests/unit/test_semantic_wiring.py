"""Tests for semantic_wiring — Phase 3B Batch 3.

Tests that eligible SemanticExecutionDecision objects are correctly
converted into executable TestScenario + TestCase pairs.
"""

from __future__ import annotations

import pytest

from testpilot.domain.schema import ApiSchema
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint, ApiRequestBody
from testpilot.domain.testing import TestCase, TestScenario
from testpilot.planner.semantic_eligibility import SemanticExecutionDecision, analyze_execution_eligibility
from testpilot.planner.semantic_wiring import build_semantic_test_cases


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_endpoint(
    *,
    body_schema: ApiSchema | None = None,
) -> ApiEndpoint:
    request_body = None
    if body_schema is not None:
        request_body = ApiRequestBody(body_schema=body_schema)
    return ApiEndpoint(
        id="ep-test",
        path="/test",
        method="POST",
        request_body=request_body,
    )


def _make_proposal(
    *,
    target_path: str = "name",
    proposed_value: object = "invalid",
    **kwargs,
) -> SemanticScenarioProposal:
    defaults = dict(
        endpoint_id="ep-test",
        name="test proposal",
        description="test desc",
        rationale="test rationale",
        category="format_violation",
        strategy="custom_value",
        target_location="body",
    )
    defaults.update(kwargs)
    return SemanticScenarioProposal(
        target_path=target_path,
        proposed_value=proposed_value,
        **defaults,
    )


def _make_eligible_decision(
    endpoint: ApiEndpoint,
    proposal: SemanticScenarioProposal,
) -> SemanticExecutionDecision:
    """Run eligibility and return the first eligible decision."""
    decisions = analyze_execution_eligibility([proposal], endpoint)
    assert decisions[0].eligible is True
    return decisions[0]


# ── Tests ───────────────────────────────────────────────────────────────────


class TestBuildSemanticTestCases:
    """Tests for build_semantic_test_cases()."""

    def test_returns_scenario_and_case(self):
        """Eligible decision produces a (TestScenario, TestCase) pair."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        pairs = build_semantic_test_cases(decision, endpoint)

        assert len(pairs) == 1
        scenario, case = pairs[0]
        assert isinstance(scenario, TestScenario)
        assert isinstance(case, TestCase)

    def test_scenario_source_is_llm(self):
        """TestScenario must have source='llm'."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, _ = build_semantic_test_cases(decision, endpoint)[0]

        assert scenario.source == "llm"

    def test_scenario_category_is_semantic_negative(self):
        """TestScenario must have category='semantic_negative'."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, _ = build_semantic_test_cases(decision, endpoint)[0]

        assert scenario.category == "semantic_negative"

    def test_scenario_has_sem_prefix_id(self):
        """TestScenario ID should use 'sem-' prefix."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, _ = build_semantic_test_cases(decision, endpoint)[0]

        assert scenario.id.startswith("sem-")

    def test_case_body_is_mutated(self):
        """TestCase body should contain the mutated value."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        _, case = build_semantic_test_cases(decision, endpoint)[0]

        assert case.body["name"] == "toolong"

    def test_case_method_and_path_match_endpoint(self):
        """TestCase method and path should match the endpoint."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        _, case = build_semantic_test_cases(decision, endpoint)[0]

        assert case.method == "POST"
        assert case.path == "/test"

    def test_case_references_scenario(self):
        """TestCase.scenario_id should match TestScenario.id."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, case = build_semantic_test_cases(decision, endpoint)[0]

        assert case.scenario_id == scenario.id

    def test_scenario_preserves_proposal_metadata(self):
        """TestScenario should preserve name, description, rationale from proposal."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="toolong",
            name="Email too long",
            description="Exceeds max length",
            rationale="Boundary check",
        )
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, _ = build_semantic_test_cases(decision, endpoint)[0]

        assert scenario.name == "Email too long"
        assert scenario.description == "Exceeds max length"
        assert scenario.rationale == "Boundary check"

    def test_scenario_has_target_location_and_path(self):
        """TestScenario should have target_location and target_path."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        scenario, _ = build_semantic_test_cases(decision, endpoint)[0]

        assert scenario.target_location == "body"
        assert scenario.target_path == "name"

    def test_non_body_location_returns_empty(self):
        """Non-body target_location should return empty list (defense in depth)."""
        # Manually construct a decision with non-body location
        proposal = SemanticScenarioProposal(
            endpoint_id="ep-test",
            name="test",
            description="test",
            rationale="test",
            category="format_violation",
            strategy="custom_value",
            target_location="query",
            target_path="q",
            proposed_value="bad",
        )
        decision = SemanticExecutionDecision(
            proposal=proposal,
            eligible=True,
            category="eligible",
            reason="test",
        )
        endpoint = _make_endpoint()

        pairs = build_semantic_test_cases(decision, endpoint)

        assert pairs == []

    def test_seen_ids_uniqueness(self):
        """Multiple calls should produce unique scenario IDs."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="name", proposed_value="toolong")
        decision = _make_eligible_decision(endpoint, proposal)

        seen: set[str] = set()
        pairs1 = build_semantic_test_cases(decision, endpoint, seen_ids=seen)
        pairs2 = build_semantic_test_cases(decision, endpoint, seen_ids=seen)

        id1 = pairs1[0][0].id
        id2 = pairs2[0][0].id
        assert id1 != id2
        assert id1 in seen
        assert id2 in seen

    def test_nested_body_mutation(self):
        """Mutation at nested body path works correctly."""
        body_schema = ApiSchema(
            type="object",
            properties={
                "address": ApiSchema(
                    type="object",
                    properties={
                        "city": ApiSchema(type="string", max_length=3),
                    },
                ),
            },
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="address.city",
            proposed_value="toolongcity",
        )
        decision = _make_eligible_decision(endpoint, proposal)

        _, case = build_semantic_test_cases(decision, endpoint)[0]

        assert case.body["address"]["city"] == "toolongcity"
