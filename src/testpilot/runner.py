"""Runner — thin orchestration for the TestPilot pipeline.

Runs: Load → Map → Select → Scenarios → Cases → Build → Execute → Validate → Report.

This is a plain function, not a framework.  CLI decides display and exit codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testpilot.config import AppConfig
from testpilot.openapi import load_openapi, map_to_api_spec, select_endpoints
from testpilot.planner import generate_scenarios
from testpilot.generator import generate_test_cases
from testpilot.generator.exceptions import TestCaseGeneratorError
from testpilot.executor import RequestBuilder, HttpExecutor
from testpilot.validator import validate
from testpilot.report import build_report, write_json_report
from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.testing import (
    ExecutionResult,
    TestCase,
    TestScenario,
    ValidationResult,
)


# ── Outcome ──────────────────────────────────────────────────────────────────


@dataclass
class RunOutcome:
    """Result of a complete TestPilot pipeline run."""

    report: dict[str, Any] = field(default_factory=dict)
    report_path: Path | None = None
    exit_code: int = 0
    endpoints_count: int = 0
    cases_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    errors_count: int = 0


# ── Public API ───────────────────────────────────────────────────────────────


def run_pipeline(config: AppConfig, output_path: Path) -> RunOutcome:
    """Execute the full TestPilot deterministic pipeline.

    Parameters
    ----------
    config:
        Runtime configuration (openapi source, base URL, filters, limits).
    output_path:
        Where to write the JSON report.

    Returns
    -------
    RunOutcome
        Contains report dict, report path, exit code, and summary counts.

    Raises
    ------
    Never raises — all errors are captured in RunOutcome.exit_code.
    Application/input errors → exit_code=2.
    Test failures → exit_code=1.
    All pass → exit_code=0.
    """
    # ── A. Load OpenAPI ──────────────────────────────────────────────────
    try:
        resolved = load_openapi(config.openapi_source)
    except Exception as exc:
        return RunOutcome(exit_code=2, report={"error": str(exc)})

    # ── B. Map to domain ─────────────────────────────────────────────────
    try:
        api_spec = map_to_api_spec(resolved)
    except Exception as exc:
        return RunOutcome(exit_code=2, report={"error": str(exc)})

    if not api_spec.endpoints:
        return RunOutcome(
            exit_code=2,
            report={"error": "No endpoints found in OpenAPI spec."},
        )

    # ── C. Select endpoints ──────────────────────────────────────────────
    selected = select_endpoints(
        api_spec.endpoints,
        include_tags=config.include_tags or None,
        exclude_tags=config.exclude_tags or None,
    )

    if not selected:
        return RunOutcome(
            exit_code=2,
            report={"error": "No endpoints matched the selected filters."},
        )

    # ── D–I. Generate, Execute, Validate ─────────────────────────────────
    all_endpoints: list[ApiEndpoint] = []
    all_scenarios: list[TestScenario] = []
    all_cases: list[TestCase] = []
    all_executions: list[ExecutionResult] = []
    all_validations: list[ValidationResult] = []

    builder = RequestBuilder(
        base_url=config.target_base_url,
        bearer_token=config.bearer_token,
        custom_headers=config.custom_headers or None,
    )
    executor = HttpExecutor(timeout_seconds=config.timeout_seconds)

    for endpoint in selected:
        all_endpoints.append(endpoint)

        # D. Generate scenarios
        scenarios = generate_scenarios(endpoint, max_cases=config.max_cases_per_endpoint)

        for scenario in scenarios:
            all_scenarios.append(scenario)

            # E. Generate test cases
            try:
                cases = generate_test_cases(endpoint, scenario)
            except TestCaseGeneratorError as exc:
                return RunOutcome(
                    exit_code=2,
                    report={
                        "error": (
                            f"Cannot generate deterministic test case for "
                            f"{endpoint.method} {endpoint.path} "
                            f"scenario={scenario.category} "
                            f"reason={exc}"
                        )
                    },
                )

            for case in cases:
                all_cases.append(case)

                # F. Build request
                request_data = builder.build(case)

                # G. Execute HTTP
                execution = executor.execute(case, request_data)
                all_executions.append(execution)

                # H. Validate
                validation = validate(endpoint, scenario, case, execution)
                all_validations.append(validation)

    # ── I. Report ────────────────────────────────────────────────────────
    try:
        report = build_report(
            endpoints=all_endpoints,
            scenarios=all_scenarios,
            cases=all_cases,
            executions=all_executions,
            validations=all_validations,
        )
        report_path = write_json_report(report, output_path)
    except Exception as exc:
        return RunOutcome(exit_code=2, report={"error": str(exc)})

    # ── Determine exit code ──────────────────────────────────────────────
    summary = report.get("summary", {})
    has_failures = any(
        not v.passed for v in all_validations
    )

    exit_code = 1 if has_failures else 0

    return RunOutcome(
        report=report,
        report_path=report_path,
        exit_code=exit_code,
        endpoints_count=summary.get("total_endpoints", 0),
        cases_count=summary.get("total_cases", 0),
        passed_count=summary.get("passed", 0),
        failed_count=summary.get("failed", 0),
        errors_count=summary.get("errors", 0),
    )
