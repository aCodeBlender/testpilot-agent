"""Deterministic Validator — T0205.

Checks whether an ``ExecutionResult`` satisfies the expectations set
by a ``TestScenario`` and the OpenAPI contract declared on an
``ApiEndpoint``.  Purely deterministic — no LLM calls.
"""

from __future__ import annotations

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.testing import (
    CheckResult,
    ExecutionResult,
    Severity,
    TestCase,
    TestScenario,
    ValidationResult,
)
from testpilot.domain.schema import ApiResponse
from testpilot.validator.exceptions import ValidatorError
from testpilot.validator.schema_validator import validate_schema


# ── Categories with known status rules ──────────────────────────────────────

_KNOWN_CATEGORIES = frozenset({
    "happy_path",
    "required_missing",
    "null",
    "wrong_type",
    "missing_auth",
    "invalid_path_id",
})


# ── Public API ──────────────────────────────────────────────────────────────


def validate(
    endpoint: ApiEndpoint,
    scenario: TestScenario,
    case: TestCase,
    execution: ExecutionResult,
) -> ValidationResult:
    """Run all deterministic checks and return an aggregated result.

    Raises ``ValidatorError`` on program / orchestration errors (mismatched
    IDs, unsupported category).
    """
    # 0. Input guards
    _check_inputs(endpoint, scenario, case, execution)

    checks: list[CheckResult] = []
    severity: Severity = "pass"

    # 1. Transport check
    transport = _check_transport(execution)
    if not transport.passed:
        return ValidationResult(
            case_id=case.id,
            passed=False,
            severity="error",
            checks=[transport],
        )

    # 2. Status check
    status = _check_status(endpoint, scenario, execution)
    checks.append(status)
    if not status.passed:
        severity = _max_severity(severity, "fail")

    # 3. Response schema check
    schema = _check_response_schema(endpoint, execution)
    checks.append(schema)
    if not schema.passed:
        severity = _max_severity(severity, "fail")

    return ValidationResult(
        case_id=case.id,
        passed=all(c.passed for c in checks),
        severity=severity,
        checks=checks,
    )


# ── Input guards ────────────────────────────────────────────────────────────


def _check_inputs(
    endpoint: ApiEndpoint,
    scenario: TestScenario,
    case: TestCase,
    execution: ExecutionResult,
) -> None:
    """Validate ID relationships — these are program errors, not test failures."""
    if scenario.endpoint_id != endpoint.id:
        raise ValidatorError(
            f"scenario.endpoint_id '{scenario.endpoint_id}' != endpoint.id '{endpoint.id}'"
        )
    if case.endpoint_id != endpoint.id:
        raise ValidatorError(
            f"case.endpoint_id '{case.endpoint_id}' != endpoint.id '{endpoint.id}'"
        )
    if case.scenario_id != scenario.id:
        raise ValidatorError(
            f"case.scenario_id '{case.scenario_id}' != scenario.id '{scenario.id}'"
        )
    if execution.case_id != case.id:
        raise ValidatorError(
            f"execution.case_id '{execution.case_id}' != case.id '{case.id}'"
        )


# ── Transport check ─────────────────────────────────────────────────────────


def _check_transport(execution: ExecutionResult) -> CheckResult:
    """Fail if the HTTP request never completed."""
    if execution.status_code is None or execution.error is not None:
        return CheckResult(
            name="transport",
            passed=False,
            expected="HTTP response received",
            actual=f"error: {execution.error}",
            message="Transport failure — request did not complete",
        )
    return CheckResult(name="transport", passed=True)


# ── Status check ────────────────────────────────────────────────────────────


def _check_status(
    endpoint: ApiEndpoint,
    scenario: TestScenario,
    execution: ExecutionResult,
) -> CheckResult:
    """Check whether the HTTP status code matches scenario expectations."""
    status_code = execution.status_code
    assert status_code is not None  # transport check already passed

    # 5xx is always a failure regardless of scenario
    if 500 <= status_code <= 599:
        return CheckResult(
            name="status",
            passed=False,
            expected=_expected_status_desc(scenario.category),
            actual=str(status_code),
            message=f"Server error {status_code}",
        )

    category = scenario.category

    if category not in _KNOWN_CATEGORIES:
        raise ValidatorError(
            f"Validator does not have status rules for category '{category}'"
        )

    if category == "happy_path":
        return _check_happy_path_status(endpoint, status_code)

    if category in ("required_missing", "null", "wrong_type", "invalid_path_id"):
        if 400 <= status_code <= 499:
            return CheckResult(name="status", passed=True)
        return CheckResult(
            name="status",
            passed=False,
            expected="4xx client error",
            actual=str(status_code),
            message=f"Negative scenario expected 4xx rejection, got {status_code}",
        )

    if category == "missing_auth":
        if status_code in (401, 403):
            return CheckResult(name="status", passed=True)
        return CheckResult(
            name="status",
            passed=False,
            expected="401 or 403",
            actual=str(status_code),
            message=f"Missing auth expected 401/403, got {status_code}",
        )

    # Should not reach here
    raise ValidatorError(f"Unhandled category '{category}'")


def _check_happy_path_status(endpoint: ApiEndpoint, status_code: int) -> CheckResult:
    """Happy path: prefer OpenAPI-declared success responses."""
    declared_success = _collect_declared_success_codes(endpoint.responses)

    if declared_success:
        # Must match one of the declared success codes
        if status_code in declared_success:
            return CheckResult(name="status", passed=True)
        return CheckResult(
            name="status",
            passed=False,
            expected=f"one of {sorted(declared_success)}",
            actual=str(status_code),
            message=f"Happy path expected declared success {sorted(declared_success)}, got {status_code}",
        )

    # No declared 2xx — fallback: any 2xx passes
    if 200 <= status_code <= 299:
        return CheckResult(name="status", passed=True)
    return CheckResult(
        name="status",
        passed=False,
        expected="2xx success",
        actual=str(status_code),
        message=f"Happy path expected 2xx, got {status_code}",
    )


def _collect_declared_success_codes(responses: dict[str, ApiResponse]) -> set[int]:
    """Collect all concrete 2xx status codes declared in responses.

    "2XX" → {200, 201, …, 299}
    "200" → {200}
    "default" → ignored (not a success declaration)
    """
    codes: set[int] = set()
    for key in responses:
        if key == "default":
            continue
        if key.upper() == "2XX":
            codes.update(range(200, 300))
        elif key.isdigit() and 200 <= int(key) <= 299:
            codes.add(int(key))
    return codes


def _expected_status_desc(category: str) -> str:
    if category == "happy_path":
        return "2xx success"
    if category in ("required_missing", "null", "wrong_type", "invalid_path_id"):
        return "4xx client error"
    if category == "missing_auth":
        return "401 or 403"
    return "appropriate status"


# ── Response schema check ───────────────────────────────────────────────────


def _check_response_schema(
    endpoint: ApiEndpoint,
    execution: ExecutionResult,
) -> CheckResult:
    """Validate response body against OpenAPI response schema if available."""
    status_code = execution.status_code
    assert status_code is not None

    # Find matching ApiResponse
    response_def = _match_response(endpoint.responses, status_code)

    if response_def is None:
        return CheckResult(
            name="response_schema",
            passed=True,
            message=f"No response schema declared for status {status_code}; schema validation skipped",
        )

    if response_def.content_schema is None:
        return CheckResult(
            name="response_schema",
            passed=True,
            message="No content schema declared; schema validation skipped",
        )

    # content_schema exists — body must be present (except 204)
    if not execution.response_body_present:
        if status_code == 204:
            return CheckResult(
                name="response_schema",
                passed=True,
                message="204 No Content — no body expected",
            )
        return CheckResult(
            name="response_schema",
            passed=False,
            expected="response body matching schema",
            actual="empty body",
            message="Response body missing but schema declared",
        )

    # response_body_present=True — validate even if response_body is None (JSON null)
    error = validate_schema(execution.response_body, response_def.content_schema, direction="response")
    if error is None:
        return CheckResult(name="response_schema", passed=True)

    return CheckResult(
        name="response_schema",
        passed=False,
        expected="valid response body",
        actual=error,
        message=f"Response schema violation: {error}",
    )


# ── Status → ApiResponse matching ───────────────────────────────────────────


def _match_response(
    responses: dict[str, ApiResponse],
    status_code: int,
) -> ApiResponse | None:
    """Find the ApiResponse matching *status_code*.

    Priority: exact → range → default.
    """
    # 1. Exact match
    exact = responses.get(str(status_code))
    if exact is not None:
        return exact

    # 2. Range match (e.g. "2XX", "4XX")
    range_key = f"{status_code // 100}XX"
    range_match = responses.get(range_key)
    if range_match is not None:
        return range_match

    # 3. Default
    return responses.get("default")


# ── Severity helpers ────────────────────────────────────────────────────────

_SEVERITY_ORDER = {"pass": 0, "warn": 1, "fail": 2, "error": 3}


def _max_severity(a: Severity, b: Severity) -> Severity:
    if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0):
        return a
    return b
