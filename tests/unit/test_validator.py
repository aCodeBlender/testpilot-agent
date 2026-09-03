"""Tests for T0205: Deterministic Validator."""

import pytest

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody, ApiResponse
from testpilot.domain.testing import TestScenario, TestCase, ExecutionResult
from testpilot.validator.validator import validate
from testpilot.validator.exceptions import ValidatorError


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(
    id: str = "ep-test",
    responses: dict[str, ApiResponse] | None = None,
) -> ApiEndpoint:
    return ApiEndpoint(
        id=id,
        path="/test",
        method="GET",
        responses=responses or {},
    )


def _scenario(
    id: str = "sc-1",
    endpoint_id: str = "ep-test",
    category: str = "happy_path",
) -> TestScenario:
    return TestScenario(
        id=id,
        endpoint_id=endpoint_id,
        source="deterministic",
        category=category,
        name=f"Test {category}",
    )


def _case(
    id: str = "tc-1",
    endpoint_id: str = "ep-test",
    scenario_id: str = "sc-1",
) -> TestCase:
    return TestCase(
        id=id,
        endpoint_id=endpoint_id,
        scenario_id=scenario_id,
        method="GET",
        path="/test",
    )


def _execution(
    case_id: str = "tc-1",
    status_code: int | None = 200,
    response_body=None,
    response_body_present: bool | None = None,
    error: str | None = None,
) -> ExecutionResult:
    # Auto-derive response_body_present if not explicitly set
    if response_body_present is None:
        response_body_present = response_body is not None
    return ExecutionResult(
        case_id=case_id,
        status_code=status_code,
        response_headers={},
        response_body=response_body,
        response_body_present=response_body_present,
        response_time_ms=10.0,
        error=error,
    )


# ── Input guards ────────────────────────────────────────────────────────────


class TestInputGuards:
    def test_scenario_endpoint_id_mismatch(self):
        with pytest.raises(ValidatorError, match="scenario.endpoint_id"):
            validate(
                _endpoint(id="ep-test"),
                _scenario(endpoint_id="ep-other"),
                _case(),
                _execution(),
            )

    def test_case_endpoint_id_mismatch(self):
        with pytest.raises(ValidatorError, match="case.endpoint_id"):
            validate(
                _endpoint(id="ep-test"),
                _scenario(),
                _case(endpoint_id="ep-other"),
                _execution(),
            )

    def test_case_scenario_id_mismatch(self):
        with pytest.raises(ValidatorError, match="case.scenario_id"):
            validate(
                _endpoint(),
                _scenario(id="sc-1"),
                _case(scenario_id="sc-other"),
                _execution(),
            )

    def test_execution_case_id_mismatch(self):
        with pytest.raises(ValidatorError, match="execution.case_id"):
            validate(
                _endpoint(),
                _scenario(),
                _case(),
                _execution(case_id="tc-other"),
            )


# ── Unsupported category ────────────────────────────────────────────────────


class TestUnsupportedCategory:
    def test_unknown_category_raises(self):
        """Categories without status rules must raise ValidatorError."""
        sc = TestScenario(
            id="sc-bad",
            endpoint_id="ep-test",
            source="llm",
            category="semantic",
            name="LLM semantic",
        )
        tc = _case(id="tc-bad", scenario_id="sc-bad")
        ex = _execution(case_id="tc-bad", status_code=200)
        with pytest.raises(ValidatorError, match="semantic"):
            validate(_endpoint(), sc, tc, ex)


# ── Transport ───────────────────────────────────────────────────────────────


class TestTransport:
    def test_timeout_is_error(self):
        result = validate(
            _endpoint(), _scenario(), _case(),
            _execution(status_code=None, error="Timeout: ..."),
        )
        assert result.passed is False
        assert result.severity == "error"
        assert len(result.checks) == 1
        assert result.checks[0].name == "transport"

    def test_connect_error_is_error(self):
        result = validate(
            _endpoint(), _scenario(), _case(),
            _execution(status_code=None, error="ConnectError: ..."),
        )
        assert result.passed is False
        assert result.severity == "error"


# ── Happy path — OpenAPI declared statuses ───────────────────────────────────


class TestHappyPath:
    def test_200_passes_no_declared(self):
        """No declared responses → any 2xx passes."""
        result = validate(
            _endpoint(), _scenario(category="happy_path"), _case(),
            _execution(status_code=200),
        )
        assert result.passed is True

    def test_201_passes_no_declared(self):
        result = validate(
            _endpoint(), _scenario(category="happy_path"), _case(),
            _execution(status_code=201),
        )
        assert result.passed is True

    def test_400_fails_no_declared(self):
        result = validate(
            _endpoint(), _scenario(category="happy_path"), _case(),
            _execution(status_code=400),
        )
        assert result.passed is False
        assert result.severity == "fail"

    def test_500_fails(self):
        result = validate(
            _endpoint(), _scenario(category="happy_path"), _case(),
            _execution(status_code=500),
        )
        assert result.passed is False
        assert result.severity == "fail"

    def test_declared_200_exact_passes(self):
        """Only status 200 declared → 200 passes."""
        ep = _endpoint(responses={"200": ApiResponse(description="OK")})
        result = validate(ep, _scenario(), _case(), _execution(status_code=200))
        assert result.passed is True

    def test_declared_200_exact_201_fails(self):
        """Only status 200 declared → 201 fails (not declared)."""
        ep = _endpoint(responses={"200": ApiResponse(description="OK")})
        result = validate(ep, _scenario(), _case(), _execution(status_code=201))
        assert result.passed is False

    def test_declared_2xx_range_passes(self):
        """2XX range declared → any 2xx passes."""
        ep = _endpoint(responses={"2XX": ApiResponse(description="Success")})
        assert validate(ep, _scenario(), _case(), _execution(status_code=200)).passed is True
        assert validate(ep, _scenario(), _case(), _execution(status_code=201)).passed is True
        assert validate(ep, _scenario(), _case(), _execution(status_code=299)).passed is True

    def test_declared_200_201_both_pass(self):
        """Both 200 and 201 declared → both pass."""
        ep = _endpoint(responses={
            "200": ApiResponse(description="OK"),
            "201": ApiResponse(description="Created"),
        })
        assert validate(ep, _scenario(), _case(), _execution(status_code=200)).passed is True
        assert validate(ep, _scenario(), _case(), _execution(status_code=201)).passed is True

    def test_declared_200_201_422_fails(self):
        """200 and 201 declared → 422 fails."""
        ep = _endpoint(responses={
            "200": ApiResponse(description="OK"),
            "201": ApiResponse(description="Created"),
        })
        result = validate(ep, _scenario(), _case(), _execution(status_code=422))
        assert result.passed is False


# ── Negative scenarios ──────────────────────────────────────────────────────


class TestNegativeScenarios:
    def test_required_missing_400_passes(self):
        result = validate(
            _endpoint(), _scenario(category="required_missing"), _case(),
            _execution(status_code=400),
        )
        assert result.passed is True

    def test_required_missing_422_passes(self):
        result = validate(
            _endpoint(), _scenario(category="required_missing"), _case(),
            _execution(status_code=422),
        )
        assert result.passed is True

    def test_required_missing_200_fails(self):
        result = validate(
            _endpoint(), _scenario(category="required_missing"), _case(),
            _execution(status_code=200),
        )
        assert result.passed is False

    def test_required_missing_500_fails(self):
        result = validate(
            _endpoint(), _scenario(category="required_missing"), _case(),
            _execution(status_code=500),
        )
        assert result.passed is False

    def test_null_400_passes(self):
        result = validate(
            _endpoint(), _scenario(category="null"), _case(),
            _execution(status_code=400),
        )
        assert result.passed is True

    def test_wrong_type_400_passes(self):
        result = validate(
            _endpoint(), _scenario(category="wrong_type"), _case(),
            _execution(status_code=400),
        )
        assert result.passed is True


# ── Auth / path ─────────────────────────────────────────────────────────────


class TestAuthPath:
    def test_missing_auth_401_passes(self):
        result = validate(
            _endpoint(), _scenario(category="missing_auth"), _case(),
            _execution(status_code=401),
        )
        assert result.passed is True

    def test_missing_auth_403_passes(self):
        result = validate(
            _endpoint(), _scenario(category="missing_auth"), _case(),
            _execution(status_code=403),
        )
        assert result.passed is True

    def test_missing_auth_200_fails(self):
        result = validate(
            _endpoint(), _scenario(category="missing_auth"), _case(),
            _execution(status_code=200),
        )
        assert result.passed is False

    def test_invalid_path_id_404_passes(self):
        result = validate(
            _endpoint(), _scenario(category="invalid_path_id"), _case(),
            _execution(status_code=404),
        )
        assert result.passed is True


# ── Status → ApiResponse matching ───────────────────────────────────────────


class TestStatusMatching:
    def test_exact_match(self):
        ep = _endpoint(responses={"200": ApiResponse(description="OK")})
        result = validate(ep, _scenario(), _case(), _execution(status_code=200))
        assert result.passed is True

    def test_range_match(self):
        ep = _endpoint(responses={"2XX": ApiResponse(description="Success")})
        result = validate(ep, _scenario(), _case(), _execution(status_code=201))
        assert result.passed is True

    def test_default_match(self):
        ep = _endpoint(responses={"default": ApiResponse(description="Other")})
        result = validate(ep, _scenario(), _case(), _execution(status_code=200))
        assert result.passed is True


# ── Schema validation ───────────────────────────────────────────────────────


class TestSchemaValidation:
    def test_object_valid(self):
        schema = ApiSchema(
            type="object",
            properties={
                "id": ApiSchema(type="integer"),
                "name": ApiSchema(type="string"),
            },
        )
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"id": 1, "name": "Alice"}))
        assert result.passed is True

    def test_required_field_missing(self):
        schema = ApiSchema(
            type="object",
            required=["id"],
            properties={"id": ApiSchema(type="integer")},
        )
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"name": "Alice"}))
        assert result.passed is False

    def test_nested_object(self):
        schema = ApiSchema(
            type="object",
            properties={
                "profile": ApiSchema(
                    type="object",
                    required=["email"],
                    properties={"email": ApiSchema(type="string")},
                ),
            },
        )
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"profile": {"email": "a@b.com"}}))
        assert result.passed is True

    def test_array(self):
        schema = ApiSchema(type="array", items=ApiSchema(type="integer"))
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body=[1, 2, 3]))
        assert result.passed is True

    def test_wrong_response_type(self):
        schema = ApiSchema(type="object")
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body="not an object"))
        assert result.passed is False

    def test_integer_rejects_bool(self):
        schema = ApiSchema(type="object", properties={"val": ApiSchema(type="integer")})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"val": True}))
        assert result.passed is False

    def test_min_max(self):
        schema = ApiSchema(type="object", properties={"age": ApiSchema(type="integer", minimum=0, maximum=150)})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body={"age": 25})).passed is True
        assert validate(ep, _scenario(), _case(), _execution(response_body={"age": -1})).passed is False

    def test_string_length(self):
        schema = ApiSchema(type="object", properties={"name": ApiSchema(type="string", min_length=1, max_length=10)})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body={"name": "Alice"})).passed is True
        assert validate(ep, _scenario(), _case(), _execution(response_body={"name": ""})).passed is False

    def test_enum(self):
        schema = ApiSchema(type="object", properties={"status": ApiSchema(type="string", enum=["active", "inactive"])})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body={"status": "active"})).passed is True
        assert validate(ep, _scenario(), _case(), _execution(response_body={"status": "unknown"})).passed is False

    def test_additional_properties_false(self):
        schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
            additional_properties=False,
        )
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body={"name": "Alice"})).passed is True
        assert validate(ep, _scenario(), _case(), _execution(response_body={"name": "Alice", "extra": 1})).passed is False

    def test_unique_items(self):
        schema = ApiSchema(type="array", items=ApiSchema(type="integer"), unique_items=True)
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body=[1, 2, 3])).passed is True
        assert validate(ep, _scenario(), _case(), _execution(response_body=[1, 1, 2])).passed is False

    def test_nullable(self):
        schema = ApiSchema(type="object", properties={"name": ApiSchema(type="string", nullable=True)})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        assert validate(ep, _scenario(), _case(), _execution(response_body={"name": None})).passed is True

    def test_no_schema_skips(self):
        """No response schema → schema check skipped, not failed."""
        ep = _endpoint(responses={"200": ApiResponse()})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"anything": 1}))
        assert result.passed is True
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert "skipped" in (schema_check.message or "")

    def test_no_matching_status_skips_schema(self):
        """Status not declared in responses → schema check skipped (but status check may still fail)."""
        ep = _endpoint(responses={"200": ApiResponse(content_schema=ApiSchema(type="object"))})
        result = validate(ep, _scenario(), _case(), _execution(status_code=404))
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is True
        assert "skipped" in (schema_check.message or "")

    def test_schema_failure_message_contains_detail(self):
        schema = ApiSchema(type="object", required=["id"], properties={"id": ApiSchema(type="integer")})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(ep, _scenario(), _case(), _execution(response_body={"name": "Alice"}))
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is False
        assert "id" in (schema_check.message or "")


# ── Empty body / JSON null with content_schema ───────────────────────────────


class TestEmptyBodySchema:
    def test_content_schema_present_but_empty_body_fails(self):
        """content_schema declared but body empty → fail."""
        schema = ApiSchema(type="object", properties={"id": ApiSchema(type="integer")})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(
            ep, _scenario(), _case(),
            _execution(response_body=None, response_body_present=False),
        )
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is False
        assert "missing" in (schema_check.message or "").lower()

    def test_204_no_content_skips_schema(self):
        """204 No Content — no body expected, schema check passes."""
        schema = ApiSchema(type="object")
        ep = _endpoint(responses={"204": ApiResponse(content_schema=schema)})
        result = validate(
            ep, _scenario(), _case(),
            _execution(status_code=204, response_body=None, response_body_present=False),
        )
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is True

    def test_json_null_with_schema_validates(self):
        """JSON null (body_present=True, body=None) → schema validates against null."""
        schema = ApiSchema(type="object", properties={"id": ApiSchema(type="integer")})
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(
            ep, _scenario(), _case(),
            _execution(response_body=None, response_body_present=True),
        )
        # null is not an object → should fail
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is False

    def test_json_null_with_nullable_schema_passes(self):
        """JSON null + nullable schema → passes."""
        schema = ApiSchema(type="object", nullable=True)
        ep = _endpoint(responses={"200": ApiResponse(content_schema=schema)})
        result = validate(
            ep, _scenario(), _case(),
            _execution(response_body=None, response_body_present=True),
        )
        schema_check = [c for c in result.checks if c.name == "response_schema"][0]
        assert schema_check.passed is True


# ── Immutability ─────────────────────────────────────────────────────────────


class TestImmutability:
    def test_does_not_mutate_inputs(self):
        ep = _endpoint(responses={"200": ApiResponse(content_schema=ApiSchema(type="object"))})
        sc = _scenario()
        tc = _case()
        ex = _execution(response_body={"a": 1})

        orig_ep = ep.model_dump()
        orig_sc = sc.model_dump()
        orig_tc = tc.model_dump()
        orig_ex = ex.model_dump()

        validate(ep, sc, tc, ex)

        assert ep.model_dump() == orig_ep
        assert sc.model_dump() == orig_sc
        assert tc.model_dump() == orig_tc
        assert ex.model_dump() == orig_ex
