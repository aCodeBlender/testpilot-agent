"""Tests for T0108-T0111: TestScenario, TestCase, ExecutionResult, ValidationResult."""

import pytest
from pydantic import ValidationError

from testpilot.domain.testing import (
    TestScenario,
    TestCase,
    ExecutionResult,
    ValidationResult,
    CheckResult,
    ScenarioTargetLocation,
)


# ── T0108: TestScenario ─────────────────────────────────────────────────────

class TestTestScenario:
    def test_minimal_scenario(self):
        s = TestScenario(
            id="sc-1",
            endpoint_id="ep-users-get",
            source="deterministic",
            category="happy_path",
            name="List users",
        )
        assert s.id == "sc-1"
        assert s.endpoint_id == "ep-users-get"
        assert s.source == "deterministic"
        assert s.category == "happy_path"
        assert s.description is None
        assert s.rationale is None
        assert s.target_location is None
        assert s.target_path is None

    def test_full_scenario(self):
        s = TestScenario(
            id="sc-missing-auth",
            endpoint_id="ep-admin-delete",
            source="deterministic",
            category="missing_auth",
            name="Delete without auth",
            description="Attempt DELETE without bearer token",
            rationale="Must return 401",
        )
        assert s.source == "deterministic"
        assert s.category == "missing_auth"
        assert s.rationale == "Must return 401"

    def test_scenario_with_target_fields(self):
        s = TestScenario(
            id="sc-1",
            endpoint_id="ep-users-post",
            source="deterministic",
            category="required_missing",
            name="Missing body.name",
            target_location="body",
            target_path="name",
        )
        assert s.target_location == "body"
        assert s.target_path == "name"

    def test_scenario_target_path_nested(self):
        s = TestScenario(
            id="sc-2",
            endpoint_id="ep-users-post",
            source="deterministic",
            category="wrong_type",
            name="Wrong type profile.email",
            target_location="body",
            target_path="profile.email",
        )
        assert s.target_path == "profile.email"

    def test_scenario_happy_path_targets_none(self):
        s = TestScenario(
            id="sc-happy",
            endpoint_id="ep-users-get",
            source="deterministic",
            category="happy_path",
            name="Happy path",
        )
        assert s.target_location is None
        assert s.target_path is None

    def test_invalid_target_location_rejected(self):
        with pytest.raises(ValidationError):
            TestScenario(
                id="sc-bad",
                endpoint_id="ep-x",
                source="deterministic",
                category="happy_path",
                name="bad",
                target_location="banana",
            )

    def test_llm_source(self):
        s = TestScenario(
            id="sc-llm-1",
            endpoint_id="ep-x",
            source="llm",
            category="semantic",
            name="LLM scenario",
        )
        assert s.source == "llm"

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            TestScenario(
                id="sc-bad",
                endpoint_id="ep-x",
                source="magic",
                category="happy_path",
                name="bad",
            )

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            TestScenario(
                id="sc-bad",
                endpoint_id="ep-x",
                source="deterministic",
                category="unknown_category",
                name="bad",
            )

    def test_id_reference_not_nested_object(self):
        """TestScenario must reference endpoint by id, not embed it."""
        s = TestScenario(
            id="sc-1",
            endpoint_id="ep-1",
            source="deterministic",
            category="happy_path",
            name="test",
        )
        data = s.model_dump()
        assert isinstance(data["endpoint_id"], str)
        # No ApiEndpoint object nested
        assert "endpoint" not in data or isinstance(data.get("endpoint"), str)

    def test_serialization_roundtrip(self):
        s = TestScenario(
            id="sc-1",
            endpoint_id="ep-1",
            source="deterministic",
            category="string_boundary",
            name="boundary",
            description="test desc",
            rationale="why",
            target_location="query",
            target_path="page",
        )
        data = s.model_dump()
        restored = TestScenario.model_validate(data)
        assert restored == s

    def test_all_deterministic_categories_valid(self):
        """Every Resume MVP deterministic category must be accepted."""
        for cat in [
            "happy_path", "required_missing", "null", "wrong_type",
            "empty_string", "string_boundary", "number_boundary",
            "invalid_enum", "invalid_path_id", "missing_auth",
        ]:
            s = TestScenario(
                id=f"sc-{cat}",
                endpoint_id="ep-1",
                source="deterministic",
                category=cat,
                name=cat,
            )
            assert s.category == cat


# ── T0109: TestCase ─────────────────────────────────────────────────────────

class TestTestCase:
    def test_minimal_case(self):
        c = TestCase(
            id="tc-1",
            endpoint_id="ep-users-get",
            scenario_id="sc-happy",
            method="GET",
            path="/users",
        )
        assert c.id == "tc-1"
        assert c.method == "GET"
        assert c.path == "/users"
        assert c.headers == {}
        assert c.query_params == {}
        assert c.path_params == {}
        assert c.cookies == {}
        assert c.body is None

    def test_post_with_body(self):
        c = TestCase(
            id="tc-create",
            endpoint_id="ep-users-post",
            scenario_id="sc-happy",
            method="POST",
            path="/users",
            headers={"Content-Type": "application/json"},
            body={"name": "Alice", "email": "alice@example.com"},
        )
        assert c.method == "POST"
        assert c.body["name"] == "Alice"

    def test_path_template_with_params(self):
        """TestCase.path stores the OpenAPI template; path_params holds raw values."""
        c = TestCase(
            id="tc-get-user",
            endpoint_id="ep-user-get",
            scenario_id="sc-happy",
            method="GET",
            path="/users/{id}",
            path_params={"id": "42"},
        )
        assert c.path == "/users/{id}"
        assert c.path_params["id"] == "42"

    def test_query_params(self):
        c = TestCase(
            id="tc-list",
            endpoint_id="ep-users-get",
            scenario_id="sc-happy",
            method="GET",
            path="/users",
            query_params={"page": "2", "limit": "10"},
        )
        assert c.query_params["page"] == "2"

    def test_invalid_method_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                id="tc-bad",
                endpoint_id="ep-x",
                scenario_id="sc-x",
                method="banana",
                path="/x",
            )

    def test_lowercase_method_rejected(self):
        with pytest.raises(ValidationError):
            TestCase(
                id="tc-bad",
                endpoint_id="ep-x",
                scenario_id="sc-x",
                method="get",
                path="/x",
            )

    def test_id_references_not_nested_objects(self):
        """TestCase references endpoint and scenario by id only."""
        c = TestCase(
            id="tc-1",
            endpoint_id="ep-1",
            scenario_id="sc-1",
            method="GET",
            path="/x",
        )
        data = c.model_dump()
        assert isinstance(data["endpoint_id"], str)
        assert isinstance(data["scenario_id"], str)

    def test_mutable_defaults_not_shared(self):
        a = TestCase(id="a", endpoint_id="ep", scenario_id="sc", method="GET", path="/a")
        b = TestCase(id="b", endpoint_id="ep", scenario_id="sc", method="GET", path="/b")
        a.headers["X-A"] = "1"
        a.query_params["q"] = "1"
        a.path_params["id"] = "1"
        a.cookies["s"] = "1"
        assert b.headers == {}
        assert b.query_params == {}
        assert b.path_params == {}
        assert b.cookies == {}

    def test_serialization_roundtrip(self):
        c = TestCase(
            id="tc-1",
            endpoint_id="ep-1",
            scenario_id="sc-1",
            method="POST",
            path="/users",
            headers={"Content-Type": "application/json"},
            query_params={"v": "1"},
            path_params={},
            cookies={"session": "abc123"},
            body={"name": "Bob"},
        )
        data = c.model_dump()
        restored = TestCase.model_validate(data)
        assert restored == c


# ── T0110: ExecutionResult ──────────────────────────────────────────────────

class TestExecutionResult:
    def test_successful_result(self):
        r = ExecutionResult(
            case_id="tc-1",
            status_code=200,
            response_headers={"Content-Type": "application/json"},
            response_body={"id": 1, "name": "Alice"},
            response_body_present=True,
            response_time_ms=42.5,
        )
        assert r.status_code == 200
        assert r.response_time_ms == 42.5
        assert r.response_body_present is True
        assert r.error is None

    def test_response_body_present_default_false(self):
        r = ExecutionResult(case_id="tc-1")
        assert r.response_body_present is False

    def test_response_body_present_json_null(self):
        """JSON null body: response_body=None but response_body_present=True."""
        r = ExecutionResult(
            case_id="tc-1",
            status_code=200,
            response_body=None,
            response_body_present=True,
        )
        assert r.response_body is None
        assert r.response_body_present is True

    def test_transport_error_status_code_none(self):
        """On transport error, status_code must be None and error must carry the reason."""
        r = ExecutionResult(
            case_id="tc-2",
            error="ConnectionRefused: [Errno 111] Connection refused",
        )
        assert r.status_code is None
        assert r.response_time_ms is None
        assert r.error is not None
        assert "Connection refused" in r.error

    def test_timeout_error(self):
        r = ExecutionResult(
            case_id="tc-3",
            error="Timeout: request took longer than 30.0s",
        )
        assert r.status_code is None
        assert "Timeout" in r.error

    def test_dns_error(self):
        r = ExecutionResult(
            case_id="tc-4",
            error="DNS resolution failed for host.invalid",
        )
        assert r.status_code is None
        assert r.response_body is None

    def test_success_without_error(self):
        r = ExecutionResult(case_id="tc-1", status_code=204)
        assert r.error is None
        assert r.status_code == 204

    def test_mutable_defaults_not_shared(self):
        a = ExecutionResult(case_id="a")
        b = ExecutionResult(case_id="b")
        a.response_headers["X-A"] = "1"
        assert b.response_headers == {}

    def test_id_reference_by_string(self):
        r = ExecutionResult(case_id="tc-1", status_code=200)
        assert isinstance(r.case_id, str)

    def test_serialization_roundtrip(self):
        r = ExecutionResult(
            case_id="tc-1",
            status_code=200,
            response_headers={"Content-Type": "application/json"},
            response_body={"ok": True},
            response_body_present=True,
            response_time_ms=10.0,
            error=None,
        )
        data = r.model_dump()
        restored = ExecutionResult.model_validate(data)
        assert restored == r


# ── T0111: CheckResult / ValidationResult ───────────────────────────────────

class TestCheckResult:
    def test_passing_check(self):
        c = CheckResult(name="status_code", passed=True, expected="200", actual="200")
        assert c.passed is True
        assert c.message is None

    def test_failing_check(self):
        c = CheckResult(
            name="response_schema",
            passed=False,
            expected="object with 'id'",
            actual="object without 'id'",
            message="Missing required field 'id'",
        )
        assert c.passed is False
        assert c.message == "Missing required field 'id'"

    def test_minimal_check(self):
        c = CheckResult(name="custom", passed=True)
        assert c.expected is None
        assert c.actual is None

    def test_serialization_roundtrip(self):
        c = CheckResult(name="s", passed=True, expected="a", actual="a", message="ok")
        data = c.model_dump()
        restored = CheckResult.model_validate(data)
        assert restored == c


class TestValidationResult:
    def test_all_passing(self):
        v = ValidationResult(
            case_id="tc-1",
            passed=True,
            severity="pass",
            checks=[
                CheckResult(name="status_code", passed=True, expected="200", actual="200"),
                CheckResult(name="schema", passed=True),
            ],
        )
        assert v.passed is True
        assert v.severity == "pass"
        assert len(v.checks) == 2

    def test_failing_result(self):
        v = ValidationResult(
            case_id="tc-2",
            passed=False,
            severity="fail",
            checks=[
                CheckResult(name="status_code", passed=True, expected="200", actual="200"),
                CheckResult(name="schema", passed=False, expected="object", actual="null"),
            ],
        )
        assert v.passed is False
        assert v.severity == "fail"

    def test_error_severity(self):
        v = ValidationResult(
            case_id="tc-3",
            passed=False,
            severity="error",
            checks=[
                CheckResult(name="connection", passed=False, message="timeout"),
            ],
        )
        assert v.severity == "error"

    def test_warn_severity(self):
        v = ValidationResult(
            case_id="tc-4",
            passed=True,
            severity="warn",
            checks=[
                CheckResult(name="deprecation", passed=True, message="endpoint is deprecated"),
            ],
        )
        assert v.severity == "warn"

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            ValidationResult(
                case_id="tc-1",
                passed=True,
                severity="critical",
                checks=[],
            )

    def test_id_reference_by_string(self):
        v = ValidationResult(
            case_id="tc-1",
            passed=True,
            severity="pass",
            checks=[],
        )
        assert isinstance(v.case_id, str)

    def test_mutable_checks_list_not_shared(self):
        a = ValidationResult(case_id="a", passed=True, severity="pass")
        b = ValidationResult(case_id="b", passed=True, severity="pass")
        a.checks.append(CheckResult(name="x", passed=True))
        assert len(b.checks) == 0

    def test_serialization_roundtrip(self):
        v = ValidationResult(
            case_id="tc-1",
            passed=False,
            severity="fail",
            checks=[
                CheckResult(name="status_code", passed=True, expected="200", actual="200"),
                CheckResult(
                    name="schema",
                    passed=False,
                    expected="object",
                    actual="null",
                    message="wrong type",
                ),
            ],
        )
        data = v.model_dump()
        restored = ValidationResult.model_validate(data)
        assert restored == v
