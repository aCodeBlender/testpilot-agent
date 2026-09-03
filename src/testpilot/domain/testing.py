"""Test execution domain models.

These models represent test scenarios, executable test cases,
execution results, and validation outcomes.  All cross-entity
references use string IDs — full objects are resolved externally
via state/collection lookups.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from testpilot.domain.schema import HttpMethod

# ── Constrained type aliases ────────────────────────────────────────────────

ScenarioSource = Literal["deterministic", "llm"]
"""Where a test scenario was generated."""

ScenarioTargetLocation = Literal["path", "query", "header", "cookie", "body", "auth"]
"""Where the mutation target lives in the HTTP request."""

ScenarioCategory = Literal[
    "happy_path",
    "required_missing",
    "null",
    "wrong_type",
    "empty_string",
    "string_boundary",
    "number_boundary",
    "invalid_enum",
    "invalid_path_id",
    "missing_auth",
    "semantic",
]
"""High-level category of what the scenario tests."""

Severity = Literal["pass", "warn", "fail", "error"]
"""Validation result severity."""


# ── TestScenario ────────────────────────────────────────────────────────────


class TestScenario(BaseModel):
    """Describes *what* to test against a single endpoint.

    Scenarios are produced by the Deterministic Generator (Phase 2)
    or the LLM Planner (Phase 3).  They do **not** carry executable
    request details — those live in ``TestCase``.
    """

    __test__ = False  # prevent pytest from collecting this domain model

    id: str = Field(description="Stable unique identifier for this scenario")
    endpoint_id: str = Field(
        description="ID of the ApiEndpoint this scenario targets",
    )
    source: ScenarioSource = Field(
        description="Which generator produced this scenario",
    )
    category: ScenarioCategory = Field(
        description="High-level test category",
    )
    name: str = Field(description="Short human-readable name")
    description: str | None = Field(default=None, description="Detailed description")
    rationale: str | None = Field(
        default=None,
        description="Why this scenario matters / what it verifies",
    )
    target_location: ScenarioTargetLocation | None = Field(
        default=None,
        description="Where the mutation target lives (None for happy_path)",
    )
    target_path: str | None = Field(
        default=None,
        description="Dotted path to the specific field being tested (e.g. 'name', 'profile.email')",
    )


# ── TestCase ────────────────────────────────────────────────────────────────


class TestCase(BaseModel):
    """An executable HTTP request definition.

    ``method`` + ``path`` + parameter/body values describe *what* to send.
    The final URL is constructed at execution time by
    ``RequestBuilder(AppConfig.target_base_url, case.path)``.
    """

    __test__ = False  # prevent pytest from collecting this domain model

    id: str = Field(description="Stable unique identifier for this test case")
    endpoint_id: str = Field(
        description="ID of the ApiEndpoint this case tests",
    )
    scenario_id: str = Field(
        description="ID of the TestScenario that produced this case",
    )
    method: HttpMethod = Field(description="HTTP method (uppercase)")
    path: str = Field(
        description="OpenAPI path template (e.g. /users/{id}), NOT the resolved path",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Request headers",
    )
    query_params: dict[str, str] = Field(
        default_factory=dict,
        description="Query string parameters",
    )
    path_params: dict[str, str] = Field(
        default_factory=dict,
        description="Path parameter values for RequestBuilder to substitute into the path template before execution",
    )
    cookies: dict[str, str] = Field(
        default_factory=dict,
        description="Cookie parameters (passed to httpx cookies kwarg)",
    )
    body: Any | None = Field(
        default=None,
        description="Request body (dict, list, or None for bodyless methods)",
    )


# ── ExecutionResult ─────────────────────────────────────────────────────────


class ExecutionResult(BaseModel):
    """Outcome of executing a single ``TestCase``.

    ``status_code`` is ``None`` when the request failed at the transport
    level (timeout, connection refused, DNS error, etc.) — in that case
    ``error`` carries the failure reason.
    """

    case_id: str = Field(description="ID of the TestCase that was executed")
    status_code: int | None = Field(
        default=None,
        description="HTTP response status code (None on transport error)",
    )
    response_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Response headers from the server",
    )
    response_body: Any | None = Field(
        default=None,
        description="Parsed response body (JSON, text, or None)",
    )
    response_body_present: bool = Field(
        default=False,
        description="True when the HTTP response had a non-empty body (even if parsed as None, e.g. JSON null)",
    )
    response_time_ms: float | None = Field(
        default=None,
        description="Round-trip time in milliseconds (None on transport error)",
    )
    error: str | None = Field(
        default=None,
        description="Error message on transport failure (None when request succeeded)",
    )


# ── CheckResult / ValidationResult ──────────────────────────────────────────


class CheckResult(BaseModel):
    """Result of a single validation check (e.g. status code match, schema conformance)."""

    name: str = Field(description="Check identifier (e.g. 'status_code', 'response_schema')")
    passed: bool = Field(description="Whether this check passed")
    expected: str | None = Field(default=None, description="Expected value (human-readable)")
    actual: str | None = Field(default=None, description="Actual value (human-readable)")
    message: str | None = Field(
        default=None,
        description="Additional context / failure explanation",
    )


class ValidationResult(BaseModel):
    """Aggregated validation outcome for a single test case.

    ``checks`` holds the per-check breakdown; ``passed`` is ``True``
    only when **all** checks passed.  ``severity`` is the highest
    severity across all checks.
    """

    case_id: str = Field(description="ID of the TestCase being validated")
    passed: bool = Field(description="True when every check passed")
    severity: Severity = Field(
        description="Highest severity across all checks",
    )
    checks: list[CheckResult] = Field(
        default_factory=list,
        description="Individual check outcomes",
    )
