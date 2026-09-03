"""Unit tests for deterministic validation guards — Phase 3B T0312.

Tests the validation layer that checks LLM proposals against endpoint schema.
"""

from __future__ import annotations

import pytest

from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint
from testpilot.planner.semantic_exceptions import SemanticPlannerError
from testpilot.planner.semantic_validation import (
    deduplicate_proposals,
    validate_proposals,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(
    id: str = "createUser",
    method: str = "POST",
    path: str = "/users",
    parameters: list[ApiParameter] | None = None,
    request_body: ApiRequestBody | None = None,
) -> ApiEndpoint:
    return ApiEndpoint(
        id=id,
        method=method,
        path=path,
        parameters=parameters or [],
        request_body=request_body,
    )


def _proposal(**overrides) -> SemanticScenarioProposal:
    """Build a valid proposal with defaults."""
    defaults = {
        "endpoint_id": "createUser",
        "name": "test proposal",
        "description": "test description",
        "rationale": "test rationale",
        "category": "format_violation",
        "target_location": "body",
        "target_path": "body.email",
        "strategy": "custom_value",
        "proposed_value": "not-an-email",
        "requires_state": False,
    }
    defaults.update(overrides)
    return SemanticScenarioProposal(**defaults)


def _user_endpoint() -> ApiEndpoint:
    """Standard test endpoint with email, name, age."""
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


# ── Guard 1: endpoint_id match ─────────────────────────────────────────────


class TestEndpointIdMatch:
    def test_matching_id_accepted(self):
        ep = _user_endpoint()
        p = _proposal(endpoint_id="createUser")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_mismatched_id_rejected(self):
        ep = _user_endpoint()
        p = _proposal(endpoint_id="NONEXISTENT")
        with pytest.raises(SemanticPlannerError, match="NONEXISTENT"):
            validate_proposals([p], ep)


# ── Guard 2: target_path exists ─────────────────────────────────────────────


class TestTargetPathExists:
    def test_valid_body_field(self):
        ep = _user_endpoint()
        p = _proposal(target_path="body.email")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_unknown_body_field_rejected(self):
        ep = _user_endpoint()
        p = _proposal(target_path="body.nonexistent")
        with pytest.raises(SemanticPlannerError, match="nonexistent"):
            validate_proposals([p], ep)

    def test_no_body_prefix_still_works(self):
        """target_path='email' (without 'body.' prefix) should work."""
        ep = _user_endpoint()
        p = _proposal(target_path="email")
        # This should fail because the body path lookup expects the raw path
        # after stripping 'body.' prefix. 'email' without prefix should still
        # be found if it's a direct property.
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_nested_body_path_valid(self):
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
        p = _proposal(target_path="body.profile.email")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_nested_body_path_invalid(self):
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
        p = _proposal(target_path="body.profile.nonexistent")
        with pytest.raises(SemanticPlannerError, match="nonexistent"):
            validate_proposals([p], ep)

    def test_traversal_into_non_object_rejected(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        p = _proposal(target_path="body.name.subfield")
        with pytest.raises(SemanticPlannerError, match="does not match"):
            validate_proposals([p], ep)

    def test_no_request_body_rejected(self):
        ep = _endpoint()  # no request body
        p = _proposal(target_path="body.email")
        with pytest.raises(SemanticPlannerError, match="does not match"):
            validate_proposals([p], ep)


# ── Guard 3: readOnly rejection ─────────────────────────────────────────────


class TestReadOnlyRejection:
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
        p = _proposal(target_path="body.id")
        with pytest.raises(SemanticPlannerError, match="readOnly"):
            validate_proposals([p], ep)

    def test_non_readonly_field_accepted(self):
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
        p = _proposal(target_path="body.name")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_readonly_nested_rejected(self):
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "meta": ApiSchema(
                            type="object",
                            properties={
                                "id": ApiSchema(type="integer", read_only=True),
                            },
                        ),
                    },
                ),
            ),
        )
        p = _proposal(target_path="body.meta.id")
        with pytest.raises(SemanticPlannerError, match="readOnly"):
            validate_proposals([p], ep)

    def test_readonly_ancestor_rejects_descendant(self):
        """A child of a readOnly object must be rejected even if the child
        itself is not marked readOnly."""
        ep = _endpoint(
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            read_only=True,
                            properties={
                                "nickname": ApiSchema(type="string"),
                            },
                        ),
                    },
                ),
            ),
        )
        p = _proposal(target_path="body.profile.nickname")
        with pytest.raises(SemanticPlannerError, match="readOnly ancestor"):
            validate_proposals([p], ep)


# ── Guard 4: target_location match ──────────────────────────────────────────


class TestTargetLocationMatch:
    def test_correct_location_accepted(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        p = _proposal(
            target_location="query",
            target_path="page",
        )
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_wrong_location_rejected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        p = _proposal(
            target_location="header",
            target_path="page",
        )
        with pytest.raises(SemanticPlannerError, match="does not match any header"):
            validate_proposals([p], ep)


# ── Guard 5: no invented paths ──────────────────────────────────────────────


class TestNoInventedPaths:
    def test_invented_param_rejected(self):
        ep = _endpoint()
        p = _proposal(
            target_location="query",
            target_path="invented_param",
        )
        with pytest.raises(SemanticPlannerError, match="does not match any query"):
            validate_proposals([p], ep)

    def test_invented_body_field_rejected(self):
        ep = _user_endpoint()
        p = _proposal(target_path="body.invented_field")
        with pytest.raises(SemanticPlannerError, match="invented_field"):
            validate_proposals([p], ep)


# ── Guard 6: multi_step_required → requires_state ──────────────────────────


class TestMultiStepRequiresState:
    def test_multi_step_with_state_accepted(self):
        ep = _user_endpoint()
        p = _proposal(
            strategy="multi_step_required",
            requires_state=True,
        )
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_multi_step_without_state_rejected_at_model_level(self):
        """multi_step_required with requires_state=False is rejected by the model
        before it even reaches validation."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="requires_state"):
            _proposal(
                strategy="multi_step_required",
                requires_state=False,
            )


# ── Guard 7: reuse_existing_value → requires_state ─────────────────────────


class TestReuseExistingValueRequiresState:
    def test_reuse_with_state_accepted(self):
        ep = _user_endpoint()
        p = _proposal(
            strategy="reuse_existing_value",
            requires_state=True,
        )
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_reuse_without_state_rejected(self):
        ep = _user_endpoint()
        p = _proposal(
            strategy="reuse_existing_value",
            requires_state=False,
        )
        with pytest.raises(SemanticPlannerError, match="requires_state"):
            validate_proposals([p], ep)


# ── Guard 8: analysis_only skips field validation ───────────────────────────


class TestAnalysisOnly:
    def test_analysis_only_no_target_required(self):
        ep = _user_endpoint()
        p = _proposal(
            strategy="analysis_only",
            target_location=None,
            target_path=None,
            proposed_value=None,
        )
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_analysis_only_with_target_validates_path(self):
        """analysis_only proposals still validate target_path against schema."""
        ep = _user_endpoint()
        p = _proposal(
            strategy="analysis_only",
            target_path="body.nonexistent",
        )
        # The validation implementation checks target_path for all strategies
        with pytest.raises(SemanticPlannerError, match="nonexistent"):
            validate_proposals([p], ep)


# ── Parameter location validation ───────────────────────────────────────────


class TestParameterValidation:
    def test_valid_query_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        p = _proposal(target_location="query", target_path="page")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_valid_header_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="X-Request-Id",
                    location="header",
                    param_schema=ApiSchema(type="string"),
                ),
            ]
        )
        p = _proposal(target_location="header", target_path="X-Request-Id")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_valid_path_param(self):
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    param_schema=ApiSchema(type="integer"),
                ),
            ]
        )
        p = _proposal(target_location="path", target_path="id")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_valid_cookie_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="session",
                    location="cookie",
                    param_schema=ApiSchema(type="string"),
                ),
            ]
        )
        p = _proposal(target_location="cookie", target_path="session")
        result = validate_proposals([p], ep)
        assert len(result) == 1

    def test_auth_location_accepted(self):
        """auth is a special location — always accepted."""
        ep = _user_endpoint()
        p = _proposal(
            target_location="auth",
            target_path=None,
            strategy="omit_field",
        )
        result = validate_proposals([p], ep)
        assert len(result) == 1


# ── Deduplication ───────────────────────────────────────────────────────────


class TestDeduplication:
    def _p(self, **overrides) -> SemanticScenarioProposal:
        return _proposal(**overrides)

    def test_exact_duplicate_removed(self):
        p1 = self._p()
        p2 = self._p()  # identical
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 1

    def test_different_category_not_deduped(self):
        p1 = self._p(category="format_violation")
        p2 = self._p(category="boundary")
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2

    def test_different_target_not_deduped(self):
        p1 = self._p(target_path="body.email")
        p2 = self._p(target_path="body.age")
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2

    def test_different_strategy_not_deduped(self):
        p1 = self._p(strategy="custom_value")
        p2 = self._p(strategy="mutate_field")
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2

    def test_different_value_not_deduped(self):
        p1 = self._p(proposed_value="not-an-email")
        p2 = self._p(proposed_value="also-not-an-email")
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2

    def test_order_preserved(self):
        """First occurrence is kept, order is deterministic.

        p1 and p1_dup are genuinely identical (same canonical JSON).
        p2 is distinct (different proposed_value).
        """
        p1 = self._p(name="First")
        p2 = self._p(name="Second", proposed_value="other")
        p1_dup = self._p(name="First")  # identical to p1
        result = deduplicate_proposals([p1, p2, p1_dup])
        assert len(result) == 2
        assert result[0].name == "First"
        assert result[1].name == "Second"

    def test_empty_list(self):
        assert deduplicate_proposals([]) == []

    def test_single_proposal(self):
        p = self._p()
        result = deduplicate_proposals([p])
        assert len(result) == 1

    def test_three_distinct_retained(self):
        proposals = [
            self._p(name="A", category="format_violation"),
            self._p(name="B", category="boundary"),
            self._p(name="C", category="semantic"),
        ]
        result = deduplicate_proposals(proposals)
        assert len(result) == 3

    def test_distinct_stateful_scenarios_retained(self):
        """Two different invalid_state + multi_step_required proposals with
        identical structural fields but different names/descriptions must
        NOT be merged."""
        p1 = self._p(
            name="Cancel already-cancelled order",
            description="Attempt to cancel an order that is already cancelled",
            rationale="State transition validation",
            category="invalid_state",
            target_location=None,
            target_path=None,
            strategy="multi_step_required",
            proposed_value=None,
            requires_state=True,
        )
        p2 = self._p(
            name="Cancel already-shipped order",
            description="Attempt to cancel an order that has already shipped",
            rationale="State transition validation",
            category="invalid_state",
            target_location=None,
            target_path=None,
            strategy="multi_step_required",
            proposed_value=None,
            requires_state=True,
        )
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2
        names = {r.name for r in result}
        assert "Cancel already-cancelled order" in names
        assert "Cancel already-shipped order" in names

    def test_int_and_string_value_do_not_collide(self):
        """Integer 1 and string '1' are different proposed values."""
        p1 = self._p(proposed_value=1)
        p2 = self._p(proposed_value="1")
        result = deduplicate_proposals([p1, p2])
        assert len(result) == 2
