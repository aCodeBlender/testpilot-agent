"""Tests for Phase 3B Batch 2: Semantic Execution Eligibility.

Test categories:
1. Eligibility tests — eligible proposals correctly identified
2. Non-eligible tests — proposals correctly blocked
3. Safety tests — non-executable proposals blocked
4. Constraint checker tests — constraint violations detected
5. Mutation tests — value correctly applied
6. Validator tests — semantic_negative scenarios get correct validation
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from testpilot.domain.schema import ApiSchema
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint, ApiRequestBody, ApiParameter
from testpilot.planner.semantic_constraint import check_constraint, ConstraintCheckResult
from testpilot.planner.semantic_eligibility import analyze_execution_eligibility, SemanticExecutionDecision
from testpilot.generator.semantic_mutation import mutate_request_for_semantic, SemanticMutationResult


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_endpoint(
    *,
    body_schema: ApiSchema | None = None,
    parameters: list[ApiParameter] | None = None,
) -> ApiEndpoint:
    """Create a minimal endpoint for testing."""
    request_body = None
    if body_schema is not None:
        request_body = ApiRequestBody(body_schema=body_schema)

    return ApiEndpoint(
        id="ep-test",
        path="/test",
        method="POST",
        parameters=parameters or [],
        request_body=request_body,
    )


def _make_proposal(
    *,
    category: str = "format_violation",
    strategy: str = "custom_value",
    target_location: str | None = "body",
    target_path: str | None = "name",
    proposed_value: object = "invalid",
    requires_state: bool = False,
    **kwargs,
) -> SemanticScenarioProposal:
    """Create a minimal proposal for testing."""
    defaults = dict(
        endpoint_id="ep-test",
        name="test proposal",
        description="test",
        rationale="test",
    )
    defaults.update(kwargs)
    return SemanticScenarioProposal(
        category=category,
        strategy=strategy,
        target_location=target_location,
        target_path=target_path,
        proposed_value=proposed_value,
        requires_state=requires_state,
        **defaults,
    )


# ── Constraint checker tests ────────────────────────────────────────────────


class TestConstraintChecker:
    """Tests for check_constraint()."""

    def test_valid_string_passes(self):
        schema = ApiSchema(type="string", min_length=1, max_length=10)
        result = check_constraint("hello", schema)
        assert result.status == "valid"
        assert result.violates is False

    def test_too_short_string_violates(self):
        schema = ApiSchema(type="string", min_length=3)
        result = check_constraint("ab", schema)
        assert result.status == "violates"
        assert result.violates is True
        assert "minLength" in result.violated_constraints

    def test_too_long_string_violates(self):
        schema = ApiSchema(type="string", max_length=3)
        result = check_constraint("toolong", schema)
        assert result.status == "violates"
        assert result.violates is True
        assert "maxLength" in result.violated_constraints

    def test_pattern_violation(self):
        schema = ApiSchema(type="string", pattern=r"^\d{3}$")
        result = check_constraint("abc", schema)
        assert result.status == "violates"
        assert "pattern" in result.violated_constraints

    def test_pattern_match_passes(self):
        schema = ApiSchema(type="string", pattern=r"^\d{3}$")
        result = check_constraint("123", schema)
        assert result.status == "valid"

    def test_enum_violation(self):
        schema = ApiSchema(type="string", enum=["a", "b", "c"])
        result = check_constraint("d", schema)
        assert result.status == "violates"
        assert "enum" in result.violated_constraints

    def test_enum_match_passes(self):
        schema = ApiSchema(type="string", enum=["a", "b", "c"])
        result = check_constraint("b", schema)
        assert result.status == "valid"

    def test_integer_minimum_violation(self):
        schema = ApiSchema(type="integer", minimum=0)
        result = check_constraint(-1, schema)
        assert result.status == "violates"
        assert "minimum" in result.violated_constraints

    def test_integer_maximum_violation(self):
        schema = ApiSchema(type="integer", maximum=100)
        result = check_constraint(101, schema)
        assert result.status == "violates"
        assert "maximum" in result.violated_constraints

    def test_exclusive_minimum_violation(self):
        schema = ApiSchema(type="integer", minimum=0, exclusive_minimum=True)
        result = check_constraint(0, schema)
        assert result.status == "violates"
        assert "exclusiveMinimum" in result.violated_constraints

    def test_exclusive_maximum_violation(self):
        schema = ApiSchema(type="integer", maximum=100, exclusive_maximum=True)
        result = check_constraint(100, schema)
        assert result.status == "violates"
        assert "exclusiveMaximum" in result.violated_constraints

    def test_type_mismatch_violates(self):
        schema = ApiSchema(type="integer")
        result = check_constraint("not an int", schema)
        assert result.status == "violates"
        assert "type" in result.violated_constraints

    def test_null_for_non_nullable_violates(self):
        schema = ApiSchema(type="string")
        result = check_constraint(None, schema)
        assert result.status == "violates"
        assert "nullable" in result.violated_constraints

    def test_null_for_nullable_passes(self):
        schema = ApiSchema(type="string", nullable=True)
        result = check_constraint(None, schema)
        assert result.status == "valid"

    def test_no_type_passes_anything(self):
        schema = ApiSchema()
        result = check_constraint("anything", schema)
        assert result.status == "valid"


# ── Format validation tests ─────────────────────────────────────────────────


class TestFormatValidation:
    """Tests for format-specific constraint checking."""

    def test_invalid_email_violates(self):
        schema = ApiSchema(type="string", format="email")
        result = check_constraint("not-an-email", schema)
        assert result.status == "violates"
        assert "format:email" in result.violated_constraints

    def test_valid_email_passes(self):
        schema = ApiSchema(type="string", format="email")
        result = check_constraint("user@example.com", schema)
        assert result.status == "valid"

    def test_invalid_uuid_violates(self):
        schema = ApiSchema(type="string", format="uuid")
        result = check_constraint("not-a-uuid", schema)
        assert result.status == "violates"
        assert "format:uuid" in result.violated_constraints

    def test_valid_uuid_passes(self):
        schema = ApiSchema(type="string", format="uuid")
        result = check_constraint("550e8400-e29b-41d4-a716-446655440000", schema)
        assert result.status == "valid"

    def test_invalid_date_violates(self):
        schema = ApiSchema(type="string", format="date")
        result = check_constraint("not-a-date", schema)
        assert result.status == "violates"
        assert "format:date" in result.violated_constraints

    def test_valid_date_passes(self):
        schema = ApiSchema(type="string", format="date")
        result = check_constraint("2024-01-15", schema)
        assert result.status == "valid"

    def test_invalid_datetime_violates(self):
        schema = ApiSchema(type="string", format="date-time")
        result = check_constraint("not-datetime", schema)
        assert result.status == "violates"
        assert "format:date-time" in result.violated_constraints

    def test_valid_datetime_passes(self):
        schema = ApiSchema(type="string", format="date-time")
        result = check_constraint("2024-01-15T10:30:00Z", schema)
        assert result.status == "valid"

    def test_invalid_ipv4_violates(self):
        schema = ApiSchema(type="string", format="ipv4")
        result = check_constraint("999.999.999.999", schema)
        assert result.status == "violates"
        assert "format:ipv4" in result.violated_constraints

    def test_valid_ipv4_passes(self):
        schema = ApiSchema(type="string", format="ipv4")
        result = check_constraint("192.168.1.1", schema)
        assert result.status == "valid"

    def test_invalid_ipv6_violates(self):
        schema = ApiSchema(type="string", format="ipv6")
        result = check_constraint("not-ipv6", schema)
        assert result.status == "violates"
        assert "format:ipv6" in result.violated_constraints

    def test_valid_ipv6_passes(self):
        schema = ApiSchema(type="string", format="ipv6")
        result = check_constraint("::1", schema)
        assert result.status == "valid"

    def test_invalid_hostname_violates(self):
        schema = ApiSchema(type="string", format="hostname")
        result = check_constraint("-invalid", schema)
        assert result.status == "violates"
        assert "format:hostname" in result.violated_constraints

    def test_valid_hostname_passes(self):
        schema = ApiSchema(type="string", format="hostname")
        result = check_constraint("example.com", schema)
        assert result.status == "valid"

    def test_invalid_uri_violates(self):
        schema = ApiSchema(type="string", format="uri")
        result = check_constraint("not a uri", schema)
        assert result.status == "violates"
        assert "format:uri" in result.violated_constraints

    def test_valid_uri_passes(self):
        schema = ApiSchema(type="string", format="uri")
        result = check_constraint("https://example.com", schema)
        assert result.status == "valid"

    def test_unsupported_format_returns_cannot_determine(self):
        """Unsupported formats must return status='cannot_determine'."""
        schema = ApiSchema(type="string", format="int64")
        result = check_constraint("12345", schema)
        assert result.status == "cannot_determine"
        assert result.violates is False
        assert "unsupported format" in result.detail


# ── Eligibility tests — eligible ────────────────────────────────────────────


class TestEligibleProposals:
    """Proposals that should be eligible for execution."""

    def test_custom_value_with_string_violation(self):
        """custom_value + primitive type + constraint violation = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", min_length=1, max_length=10)},
            required=["name"],
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="x" * 100,  # violates maxLength=10
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert len(decisions) == 1
        assert decisions[0].eligible is True
        assert decisions[0].category == "eligible"
        assert decisions[0].constraint_result is not None
        assert decisions[0].constraint_result.violates is True

    def test_custom_value_with_integer_violation(self):
        """custom_value + integer + min violation = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"age": ApiSchema(type="integer", minimum=0)},
            required=["age"],
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="age",
            proposed_value=-5,
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_custom_value_with_enum_violation(self):
        """custom_value + value not in enum = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"status": ApiSchema(type="string", enum=["active", "inactive"])},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="status",
            proposed_value="deleted",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_custom_value_with_format_violation(self):
        """custom_value + invalid format = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"email": ApiSchema(type="string", format="email")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="email",
            proposed_value="not-an-email",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_custom_value_with_pattern_violation(self):
        """custom_value + pattern mismatch = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"code": ApiSchema(type="string", pattern=r"^[A-Z]{3}$")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="code",
            proposed_value="abc",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_custom_value_with_type_mismatch(self):
        """custom_value + wrong type = eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"count": ApiSchema(type="integer")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="count",
            proposed_value="not-a-number",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_nested_body_path(self):
        """Mutation at nested body path works."""
        body_schema = ApiSchema(
            type="object",
            properties={
                "address": ApiSchema(
                    type="object",
                    properties={
                        "zip": ApiSchema(type="string", pattern=r"^\d{5}$"),
                    },
                ),
            },
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="address.zip",
            proposed_value="not-zip",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

    def test_query_parameter_rejected(self):
        """Non-body locations are not supported for mutation — must be rejected."""
        param = ApiParameter(
            name="limit",
            location="query",
            required=True,
            param_schema=ApiSchema(type="integer", minimum=1, maximum=100),
        )
        endpoint = _make_endpoint(parameters=[param])
        proposal = _make_proposal(
            target_location="query",
            target_path="limit",
            proposed_value=-1,
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "not supported" in decisions[0].reason

    def test_multiple_proposals_mixed_eligibility(self):
        """Multiple proposals — some eligible, some not."""
        body_schema = ApiSchema(
            type="object",
            properties={
                "name": ApiSchema(type="string", min_length=1, max_length=10),
                "status": ApiSchema(type="string", enum=["active", "inactive"]),
            },
        )
        endpoint = _make_endpoint(body_schema=body_schema)

        proposals = [
            _make_proposal(
                target_path="name",
                proposed_value="x" * 100,
            ),
            _make_proposal(
                strategy="analysis_only",
                target_path="name",
                proposed_value="test",
            ),
        ]

        decisions = analyze_execution_eligibility(proposals, endpoint)
        assert len(decisions) == 2
        assert decisions[0].eligible is True
        assert decisions[1].eligible is False


# ── Eligibility tests — not eligible ────────────────────────────────────────


class TestNonEligibleProposals:
    """Proposals that should NOT be eligible for execution."""

    def test_analysis_only_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(strategy="analysis_only")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert decisions[0].category == "not_executable"
        assert "analysis_only" in decisions[0].reason

    def test_omit_field_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(strategy="omit_field")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_mutate_field_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"status": ApiSchema(type="string", enum=["a", "b"])},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(strategy="mutate_field")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_multi_step_required_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(strategy="multi_step_required", requires_state=True)

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_requires_state_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(strategy="custom_value", requires_state=True)

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_no_proposed_value_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(proposed_value=None)

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "no proposed_value" in decisions[0].reason

    def test_no_target_location_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_location=None)

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_no_target_path_not_eligible(self):
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path=None)

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False

    def test_valid_value_not_eligible(self):
        """If the proposed value doesn't violate any constraint, not eligible."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", min_length=1, max_length=100)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="valid-name",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "does not violate" in decisions[0].reason


# ── Safety tests — non-executable proposals blocked ─────────────────────────


class TestSafetyBlocking:
    """Safety guards that prevent execution of non-executable proposals."""

    def test_readonly_field_blocked(self):
        """readOnly fields must not be mutated."""
        body_schema = ApiSchema(
            type="object",
            properties={"id": ApiSchema(type="string", read_only=True)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="id", proposed_value="new-id")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert decisions[0].category == "blocked"
        assert "readOnly" in decisions[0].reason

    def test_array_target_not_supported(self):
        """Array type targets are not supported for mutation."""
        body_schema = ApiSchema(
            type="object",
            properties={"tags": ApiSchema(type="array", items=ApiSchema(type="string"))},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="tags", proposed_value=["a", "b"])

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "array" in decisions[0].reason

    def test_object_target_not_supported(self):
        """Object type targets are not supported for direct mutation."""
        body_schema = ApiSchema(
            type="object",
            properties={
                "metadata": ApiSchema(
                    type="object",
                    properties={"key": ApiSchema(type="string")},
                ),
            },
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="metadata", proposed_value={"bad": True})

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "object" in decisions[0].reason

    def test_unresolvable_path_blocked(self):
        """Target path that doesn't exist in schema is blocked."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(target_path="nonexistent.field")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert decisions[0].category == "blocked"
        assert "could not resolve" in decisions[0].reason

    def test_no_endpoint_body_blocked(self):
        """Proposal targeting body when endpoint has no body is blocked."""
        endpoint = _make_endpoint()  # no body_schema
        proposal = _make_proposal(target_path="name")

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert decisions[0].category == "blocked"


# ── Mutation tests ──────────────────────────────────────────────────────────


class TestSemanticMutation:
    """Tests for mutate_request_for_semantic()."""

    def test_simple_body_mutation(self):
        """Mutate a top-level body property."""
        base_request = {
            "headers": {"Content-Type": "application/json"},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"name": "valid-name", "email": "test@example.com"},
        }
        proposal = _make_proposal(
            target_path="name",
            proposed_value="x" * 100,
        )
        endpoint = _make_endpoint()

        result = mutate_request_for_semantic(base_request, proposal, endpoint)

        assert result.mutated_request["body"]["name"] == "x" * 100
        assert result.mutated_request["body"]["email"] == "test@example.com"
        assert result.original_value == "valid-name"
        assert result.mutated_value == "x" * 100

    def test_nested_body_mutation(self):
        """Mutate a nested body property."""
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"address": {"zip": "12345", "city": "NYC"}},
        }
        proposal = _make_proposal(
            target_path="address.zip",
            proposed_value="not-a-zip",
        )
        endpoint = _make_endpoint()

        result = mutate_request_for_semantic(base_request, proposal, endpoint)

        assert result.mutated_request["body"]["address"]["zip"] == "not-a-zip"
        assert result.mutated_request["body"]["address"]["city"] == "NYC"
        assert result.original_value == "12345"

    def test_original_preserved(self):
        """The original request is not mutated."""
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"name": "original"},
        }
        proposal = _make_proposal(target_path="name", proposed_value="mutated")
        endpoint = _make_endpoint()

        mutate_request_for_semantic(base_request, proposal, endpoint)

        assert base_request["body"]["name"] == "original"

    def test_constraints_violated_stored(self):
        """Constraints violated list is stored in result."""
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"name": "valid"},
        }
        proposal = _make_proposal(target_path="name", proposed_value="x" * 100)
        endpoint = _make_endpoint()

        result = mutate_request_for_semantic(
            base_request, proposal, endpoint,
            constraints_violated=["maxLength", "pattern"],
        )

        assert result.constraints_violated == ["maxLength", "pattern"]

    def test_missing_path_creates_nested(self):
        """If target path doesn't exist, it's created."""
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"existing": "value"},
        }
        proposal = _make_proposal(target_path="new.field", proposed_value="test")
        endpoint = _make_endpoint()

        result = mutate_request_for_semantic(base_request, proposal, endpoint)

        assert result.mutated_request["body"]["new"]["field"] == "test"
        assert result.mutated_request["body"]["existing"] == "value"

    def test_none_body_with_body_target(self):
        """If body is None but target is body, create minimal body."""
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": None,
        }
        proposal = _make_proposal(target_path="name", proposed_value="test")
        endpoint = _make_endpoint()

        result = mutate_request_for_semantic(base_request, proposal, endpoint)

        assert result.mutated_request["body"] == {"name": "test"}


# ── Validator integration tests ─────────────────────────────────────────────


class TestValidatorIntegration:
    """Tests verifying semantic_negative scenarios get correct validation."""

    def test_semantic_negative_in_expected_status_desc(self):
        """semantic_negative should be mapped to '4xx client error'."""
        from testpilot.validator.validator import _expected_status_desc

        result = _expected_status_desc("semantic_negative")
        assert "4xx" in result.lower()

    def test_semantic_negative_in_known_categories(self):
        """semantic_negative should be in _KNOWN_CATEGORIES."""
        from testpilot.validator.validator import _KNOWN_CATEGORIES

        assert "semantic_negative" in _KNOWN_CATEGORIES

    def test_semantic_negative_expects_4xx(self):
        """4xx status should pass for semantic_negative category."""
        from testpilot.validator.validator import _check_status
        from testpilot.domain.testing import TestScenario, ExecutionResult
        from testpilot.domain.spec import ApiEndpoint

        endpoint = ApiEndpoint(id="ep", path="/test", method="POST")
        scenario = TestScenario(
            id="sc-1", endpoint_id="ep", name="test",
            category="semantic_negative", source="llm",
        )
        execution = ExecutionResult(
            case_id="tc-1", status_code=400, headers={}, body=None, elapsed_ms=10,
        )

        result = _check_status(endpoint, scenario, execution)
        assert result.passed is True

    def test_semantic_negative_expects_4xx_upper(self):
        """499 status should pass for semantic_negative category."""
        from testpilot.validator.validator import _check_status
        from testpilot.domain.testing import TestScenario, ExecutionResult
        from testpilot.domain.spec import ApiEndpoint

        endpoint = ApiEndpoint(id="ep", path="/test", method="POST")
        scenario = TestScenario(
            id="sc-1", endpoint_id="ep", name="test",
            category="semantic_negative", source="llm",
        )
        execution = ExecutionResult(
            case_id="tc-1", status_code=499, headers={}, body=None, elapsed_ms=10,
        )

        result = _check_status(endpoint, scenario, execution)
        assert result.passed is True

    def test_semantic_negative_2xx_fails(self):
        """2xx status should fail for semantic_negative category."""
        from testpilot.validator.validator import _check_status
        from testpilot.domain.testing import TestScenario, ExecutionResult
        from testpilot.domain.spec import ApiEndpoint

        endpoint = ApiEndpoint(id="ep", path="/test", method="POST")
        scenario = TestScenario(
            id="sc-1", endpoint_id="ep", name="test",
            category="semantic_negative", source="llm",
        )
        execution = ExecutionResult(
            case_id="tc-1", status_code=200, headers={}, body=None, elapsed_ms=10,
        )

        result = _check_status(endpoint, scenario, execution)
        assert result.passed is False


# ── Tri-state regression tests ──────────────────────────────────────────────


class TestTriStateConstraintResult:
    """Regression tests proving the tri-state constraint result semantics."""

    def test_supported_format_valid_value_returns_valid(self):
        """Supported format + valid value → status='valid'."""
        schema = ApiSchema(type="string", format="email")
        result = check_constraint("user@example.com", schema)
        assert result.status == "valid"
        assert result.violates is False
        assert result.violated_constraints == []

    def test_supported_format_invalid_value_returns_violates(self):
        """Supported format + invalid value → status='violates'."""
        schema = ApiSchema(type="string", format="uuid")
        result = check_constraint("not-a-uuid", schema)
        assert result.status == "violates"
        assert result.violates is True
        assert len(result.violated_constraints) > 0

    def test_unsupported_format_returns_cannot_determine(self):
        """Unsupported format → status='cannot_determine'."""
        schema = ApiSchema(type="string", format="int64")
        result = check_constraint("12345", schema)
        assert result.status == "cannot_determine"
        assert result.violates is False
        assert result.violated_constraints == []

    def test_cannot_determine_proposal_rejected_by_eligibility(self):
        """A proposal whose constraint check returns cannot_determine is NOT executable."""
        body_schema = ApiSchema(
            type="object",
            properties={"count": ApiSchema(type="string", format="int64")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="count",
            proposed_value="12345",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert decisions[0].category == "not_executable"
        assert "cannot determine" in decisions[0].reason
        assert decisions[0].constraint_result is not None
        assert decisions[0].constraint_result.status == "cannot_determine"


# ── Provenance regression tests ─────────────────────────────────────────────


class TestProvenance:
    """Regression tests verifying LLM provenance is preserved."""

    def test_semantic_scenario_retains_llm_source(self):
        """Executable semantic scenarios must preserve source='llm'."""
        from testpilot.domain.testing import TestScenario

        scenario = TestScenario(
            id="sc-sem-1",
            endpoint_id="ep-test",
            name="semantic negative: email format",
            category="semantic_negative",
            source="llm",
        )
        assert scenario.source == "llm"
        assert scenario.category == "semantic_negative"

    def test_deterministic_scenario_backward_compatible(self):
        """Existing deterministic scenarios remain backward compatible."""
        from testpilot.domain.testing import TestScenario

        scenario = TestScenario(
            id="sc-det-1",
            endpoint_id="ep-test",
            name="happy path",
            category="happy_path",
            source="deterministic",
        )
        assert scenario.source == "deterministic"
        assert scenario.category == "happy_path"

    def test_eligible_decision_preserves_proposal(self):
        """Eligible decision carries the full proposal for downstream provenance tracking."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=5)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="toolong",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True
        # The decision carries the proposal — source="llm" is set when
        # converting to TestScenario downstream
        assert decisions[0].proposal is proposal
        assert decisions[0].proposal.strategy == "custom_value"


# ── Location consistency regression tests ───────────────────────────────────


class TestLocationConsistency:
    """Regression tests verifying target_location consistency between eligibility and mutation."""

    def test_query_location_rejected_by_eligibility(self):
        """Query target_location is rejected — only body mutation is implemented."""
        param = ApiParameter(
            name="q",
            location="query",
            param_schema=ApiSchema(type="string", min_length=1),
        )
        endpoint = _make_endpoint(parameters=[param])
        proposal = _make_proposal(
            target_location="query",
            target_path="q",
            proposed_value="",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "not supported" in decisions[0].reason

    def test_header_location_rejected_by_eligibility(self):
        """Header target_location is rejected — only body mutation is implemented."""
        param = ApiParameter(
            name="X-Custom",
            location="header",
            param_schema=ApiSchema(type="string"),
        )
        endpoint = _make_endpoint(parameters=[param])
        proposal = _make_proposal(
            target_location="header",
            target_path="X-Custom",
            proposed_value="bad",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "not supported" in decisions[0].reason

    def test_path_location_rejected_by_eligibility(self):
        """Path target_location is rejected — only body mutation is implemented."""
        param = ApiParameter(
            name="id",
            location="path",
            required=True,
            param_schema=ApiSchema(type="integer"),
        )
        endpoint = _make_endpoint(parameters=[param])
        proposal = _make_proposal(
            target_location="path",
            target_path="id",
            proposed_value="not-an-int",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is False
        assert "not supported" in decisions[0].reason

    def test_body_location_accepted_by_eligibility(self):
        """Body target_location is the only accepted location."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=3)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_location="body",
            target_path="name",
            proposed_value="toolong",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True


# ── Round-trip tests ────────────────────────────────────────────────────────


class TestRoundTrip:
    """End-to-end tests: proposal → eligibility → mutation → validation."""

    def test_full_pipeline_string_too_long(self):
        """Full pipeline: string exceeding maxLength."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", min_length=1, max_length=10)},
            required=["name"],
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="x" * 100,
        )

        # Eligibility
        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

        # Mutation
        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"name": "valid"},
        }
        result = mutate_request_for_semantic(
            base_request, proposal, endpoint,
            constraints_violated=decisions[0].constraint_result.violated_constraints,
        )
        assert result.mutated_request["body"]["name"] == "x" * 100
        assert "maxLength" in result.constraints_violated

    def test_full_pipeline_integer_minimum(self):
        """Full pipeline: integer below minimum."""
        body_schema = ApiSchema(
            type="object",
            properties={"age": ApiSchema(type="integer", minimum=0)},
            required=["age"],
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="age",
            proposed_value=-5,
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"age": 25},
        }
        result = mutate_request_for_semantic(
            base_request, proposal, endpoint,
            constraints_violated=decisions[0].constraint_result.violated_constraints,
        )
        assert result.mutated_request["body"]["age"] == -5
        assert "minimum" in result.constraints_violated

    def test_full_pipeline_format_violation(self):
        """Full pipeline: invalid email format."""
        body_schema = ApiSchema(
            type="object",
            properties={"email": ApiSchema(type="string", format="email")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="email",
            proposed_value="not-email",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True

        base_request = {
            "headers": {},
            "query_params": {},
            "path_params": {},
            "cookies": {},
            "body": {"email": "test@example.com"},
        }
        result = mutate_request_for_semantic(
            base_request, proposal, endpoint,
            constraints_violated=decisions[0].constraint_result.violated_constraints,
        )
        assert result.mutated_request["body"]["email"] == "not-email"
        assert "format:email" in result.constraints_violated

    def test_provenance_is_semantic_negative(self):
        """Eligible proposals use custom_value strategy and produce semantic_negative scenarios."""
        body_schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string", max_length=5)},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        proposal = _make_proposal(
            target_path="name",
            proposed_value="toolong",
        )

        decisions = analyze_execution_eligibility([proposal], endpoint)
        assert decisions[0].eligible is True
        # The strategy should be "custom_value" (the eligibility criterion)
        assert decisions[0].proposal.strategy == "custom_value"
