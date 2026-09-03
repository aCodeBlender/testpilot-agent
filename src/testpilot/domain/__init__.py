"""Domain models for TestPilot."""

from testpilot.domain.spec import ApiSpec, ApiEndpoint
from testpilot.domain.schema import (
    ApiSchema,
    ApiParameter,
    ApiRequestBody,
    ApiResponse,
    HttpMethod,
    ParameterLocation,
)
from testpilot.domain.testing import (
    TestScenario,
    TestCase,
    ExecutionResult,
    ValidationResult,
    CheckResult,
    ScenarioSource,
    ScenarioCategory,
    ScenarioTargetLocation,
    Severity,
)

__all__ = [
    "ApiSpec",
    "ApiEndpoint",
    "ApiSchema",
    "ApiParameter",
    "ApiRequestBody",
    "ApiResponse",
    "HttpMethod",
    "ParameterLocation",
    "TestScenario",
    "TestCase",
    "ExecutionResult",
    "ValidationResult",
    "CheckResult",
    "ScenarioSource",
    "ScenarioCategory",
    "ScenarioTargetLocation",
    "Severity",
]
