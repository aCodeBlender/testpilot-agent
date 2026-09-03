"""Unit tests for Semantic Scenario Planner — Phase 3B T0311.

All LLM calls are mocked. No real API calls, no token consumption.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody
from testpilot.domain.spec import ApiEndpoint
from testpilot.planner.semantic_exceptions import SemanticPlannerError
from testpilot.planner.semantic_planner import (
    build_endpoint_prompt_context,
    plan_semantic_scenarios,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(
    id: str = "createUser",
    method: str = "POST",
    path: str = "/users",
    summary: str = "Create user",
    description: str = "",
    tags: list[str] | None = None,
    parameters: list[ApiParameter] | None = None,
    request_body: ApiRequestBody | None = None,
) -> ApiEndpoint:
    return ApiEndpoint(
        id=id,
        method=method,
        path=path,
        summary=summary,
        description=description,
        tags=tags or [],
        parameters=parameters or [],
        request_body=request_body,
    )


def _mock_llm_client(response: str | list) -> MagicMock:
    """Create a mock LLM client."""
    client = MagicMock()
    if isinstance(response, list):
        client.call.return_value = json.dumps(response)
    else:
        client.call.return_value = response
    return client


def _user_endpoint() -> ApiEndpoint:
    """Standard test endpoint: POST /users with email, name, age."""
    return _endpoint(
        request_body=ApiRequestBody(
            required=True,
            body_schema=ApiSchema(
                type="object",
                required=["email", "name"],
                properties={
                    "email": ApiSchema(type="string", format="email"),
                    "name": ApiSchema(type="string"),
                    "age": ApiSchema(type="integer", minimum=0, maximum=150),
                },
            ),
        ),
    )


def _valid_proposal(**overrides) -> dict:
    """Build a valid proposal dict with defaults."""
    base = {
        "endpoint_id": "createUser",
        "name": "Invalid email format",
        "description": "Send a malformed email address",
        "rationale": "Email format validation",
        "category": "format_violation",
        "target_location": "body",
        "target_path": "body.email",
        "strategy": "custom_value",
        "proposed_value": "not-an-email",
        "requires_state": False,
    }
    base.update(overrides)
    return base


# ── build_endpoint_prompt_context ───────────────────────────────────────────


class TestBuildEndpointPromptContext:
    def test_basic_fields(self):
        ep = _endpoint()
        ctx = build_endpoint_prompt_context(ep)
        assert ctx["endpoint_id"] == "createUser"
        assert ctx["method"] == "POST"
        assert ctx["path"] == "/users"
        assert ctx["summary"] == "Create user"

    def test_parameters_included(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    required=True,
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        ctx = build_endpoint_prompt_context(ep)
        assert len(ctx["parameters"]) == 1
        assert ctx["parameters"][0]["name"] == "page"
        assert ctx["parameters"][0]["location"] == "query"
        assert ctx["parameters"][0]["schema"]["type"] == "integer"

    def test_request_body_schema(self):
        ep = _user_endpoint()
        ctx = build_endpoint_prompt_context(ep)
        assert "request_body" in ctx
        schema = ctx["request_body"]["schema"]
        assert schema["type"] == "object"
        assert "email" in schema["properties"]
        assert schema["properties"]["email"]["format"] == "email"

    def test_no_secrets(self):
        """Context must not contain API keys, tokens, or auth values."""
        ep = _endpoint()
        ctx = build_endpoint_prompt_context(ep)
        ctx_str = json.dumps(ctx)
        assert "api_key" not in ctx_str.lower()
        assert "bearer" not in ctx_str.lower()
        assert "token" not in ctx_str.lower()
        assert "password" not in ctx_str.lower()

    def test_readonly_marked(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "id": ApiSchema(type="integer", read_only=True),
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        ctx = build_endpoint_prompt_context(ep)
        schema = ctx["request_body"]["schema"]
        assert schema["properties"]["id"].get("readOnly") is True
        assert schema["properties"]["name"].get("readOnly") is None

    def test_nested_body_schema(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            properties={
                                "email": ApiSchema(type="string", format="email"),
                            },
                        ),
                    },
                ),
            ),
        )
        ctx = build_endpoint_prompt_context(ep)
        schema = ctx["request_body"]["schema"]
        assert "profile" in schema["properties"]
        assert "email" in schema["properties"]["profile"]["properties"]


# ── plan_semantic_scenarios ─────────────────────────────────────────────────


class TestPlanSemanticScenarios:
    def test_valid_single_proposal(self):
        ep = _user_endpoint()
        proposals = [_valid_proposal()]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 1
        assert result[0].name == "Invalid email format"
        assert result[0].category == "format_violation"

    def test_valid_multiple_proposals(self):
        ep = _user_endpoint()
        proposals = [
            _valid_proposal(),
            _valid_proposal(
                name="Duplicate email",
                category="duplicate_resource",
                strategy="multi_step_required",
                requires_state=True,
                proposed_value=None,
            ),
        ]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 2

    def test_empty_list_valid(self):
        """LLM returns [] — no semantic scenarios for this endpoint."""
        ep = _endpoint()
        client = _mock_llm_client([])
        result = plan_semantic_scenarios(ep, client)
        assert result == []

    def test_invalid_json_rejected(self):
        ep = _endpoint()
        client = _mock_llm_client("not valid json {{{")
        with pytest.raises(SemanticPlannerError, match="invalid JSON"):
            plan_semantic_scenarios(ep, client)

    def test_non_array_rejected(self):
        """LLM returns a single object instead of an array."""
        ep = _endpoint()
        client = _mock_llm_client(json.dumps(_valid_proposal()))
        with pytest.raises(SemanticPlannerError, match="JSON array"):
            plan_semantic_scenarios(ep, client)

    def test_invalid_proposal_schema_rejected(self):
        """LLM returns array with missing required fields."""
        ep = _endpoint()
        client = _mock_llm_client([{"completely": "wrong"}])
        with pytest.raises(SemanticPlannerError, match="does not match schema"):
            plan_semantic_scenarios(ep, client)

    def test_markdown_fences_stripped(self):
        ep = _user_endpoint()
        proposals = [_valid_proposal()]
        raw = f"```json\n{json.dumps(proposals)}\n```"
        client = _mock_llm_client(raw)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 1

    def test_llm_call_failure_raises(self):
        ep = _endpoint()
        client = MagicMock()
        client.call.side_effect = Exception("connection refused")
        with pytest.raises(SemanticPlannerError, match="LLM call failed"):
            plan_semantic_scenarios(ep, client)

    def test_focus_areas_in_prompt(self):
        """Focus areas should appear in the user prompt."""
        ep = _user_endpoint()
        client = _mock_llm_client([])
        plan_semantic_scenarios(ep, client, focus_areas=["authorization", "boundary"])
        call_args = client.call.call_args
        user_prompt = call_args[0][1]
        assert "authorization" in user_prompt
        assert "boundary" in user_prompt


# ── Hallucination guards (via validation) ───────────────────────────────────


class TestHallucinationGuards:
    def test_unknown_endpoint_id_rejected(self):
        ep = _user_endpoint()
        proposals = [_valid_proposal(endpoint_id="NONEXISTENT")]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="NONEXISTENT"):
            plan_semantic_scenarios(ep, client)

    def test_unknown_body_field_rejected(self):
        ep = _user_endpoint()
        proposals = [_valid_proposal(target_path="body.nonexistent")]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="nonexistent"):
            plan_semantic_scenarios(ep, client)

    def test_wrong_parameter_location_rejected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        proposals = [_valid_proposal(
            endpoint_id="createUser",
            target_location="header",
            target_path="page",
            strategy="custom_value",
        )]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="does not match any header"):
            plan_semantic_scenarios(ep, client)

    def test_readonly_field_rejected(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "id": ApiSchema(type="integer", read_only=True),
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        proposals = [_valid_proposal(
            endpoint_id="createUser",
            target_path="body.id",
            strategy="custom_value",
        )]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="readOnly"):
            plan_semantic_scenarios(ep, client)

    def test_nonexistent_nested_field_rejected(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            properties={
                                "email": ApiSchema(type="string"),
                            },
                        ),
                    },
                ),
            ),
        )
        proposals = [_valid_proposal(
            endpoint_id="createUser",
            target_path="body.profile.nonexistent",
        )]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="nonexistent"):
            plan_semantic_scenarios(ep, client)

    def test_analysis_only_skips_field_validation(self):
        """analysis_only proposals don't need target_path validation."""
        ep = _user_endpoint()
        proposals = [_valid_proposal(
            strategy="analysis_only",
            target_location=None,
            target_path=None,
            proposed_value=None,
        )]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 1
        assert result[0].strategy == "analysis_only"


# ── Stateful classification ────────────────────────────────────────────────


class TestStatefulClassification:
    def test_duplicate_resource_requires_state(self):
        """duplicate_resource with multi_step_required sets requires_state."""
        ep = _user_endpoint()
        proposals = [_valid_proposal(
            name="Duplicate email registration",
            category="duplicate_resource",
            strategy="multi_step_required",
            requires_state=True,
            proposed_value=None,
        )]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert result[0].requires_state is True
        assert result[0].strategy == "multi_step_required"

    def test_multi_step_without_state_rejected(self):
        """multi_step_required with requires_state=False is rejected."""
        ep = _user_endpoint()
        proposals = [_valid_proposal(
            strategy="multi_step_required",
            requires_state=False,
        )]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="requires_state"):
            plan_semantic_scenarios(ep, client)

    def test_reuse_existing_value_requires_state(self):
        """reuse_existing_value with requires_state=False is rejected."""
        ep = _user_endpoint()
        proposals = [_valid_proposal(
            strategy="reuse_existing_value",
            requires_state=False,
        )]
        client = _mock_llm_client(proposals)
        with pytest.raises(SemanticPlannerError, match="requires_state"):
            plan_semantic_scenarios(ep, client)

    def test_proposals_are_not_test_scenarios(self):
        """Proposals are SemanticScenarioProposal, not TestScenario."""
        ep = _user_endpoint()
        proposals = [_valid_proposal(
            name="Duplicate email",
            category="duplicate_resource",
            strategy="multi_step_required",
            requires_state=True,
        )]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        from testpilot.domain.semantic import SemanticScenarioProposal
        from testpilot.domain.testing import TestScenario
        assert isinstance(result[0], SemanticScenarioProposal)
        assert not isinstance(result[0], TestScenario)


# ── Deduplication ───────────────────────────────────────────────────────────


class TestDeduplication:
    def test_exact_duplicate_removed(self):
        ep = _user_endpoint()
        proposal = _valid_proposal()
        proposals = [proposal, proposal]  # exact same dict twice
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 1

    def test_distinct_scenarios_retained(self):
        """Different categories/targets are not deduped."""
        ep = _user_endpoint()
        proposals = [
            _valid_proposal(
                name="Invalid email",
                category="format_violation",
                target_path="body.email",
            ),
            _valid_proposal(
                name="Boundary age",
                category="boundary",
                target_path="body.age",
                proposed_value=200,
            ),
        ]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 2

    def test_deterministic_order(self):
        """First occurrence is kept, order is stable.

        p1 and p1_dup are genuinely identical (same canonical JSON).
        p2 is distinct (different proposed_value).
        """
        ep = _user_endpoint()
        p1 = _valid_proposal(name="First")
        p2 = _valid_proposal(name="Second", proposed_value="other")
        p1_dup = _valid_proposal(name="First")  # identical to p1
        proposals = [p1, p2, p1_dup]
        client = _mock_llm_client(proposals)
        result = plan_semantic_scenarios(ep, client)
        assert len(result) == 2
        assert result[0].name == "First"
        assert result[1].name == "Second"
