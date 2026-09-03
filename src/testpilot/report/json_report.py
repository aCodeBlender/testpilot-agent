"""JSON Report builder and writer — T0206.

``build_report`` is a pure function that projects already-produced test
results into a deterministic, redacted JSON-serialisable dict.

``write_json_report`` persists that dict to disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.testing import (
    ExecutionResult,
    TestCase,
    TestScenario,
    ValidationResult,
)
from testpilot.report.exceptions import ReportError
from testpilot.report.redact import (
    redact_body,
    redact_cookies,
    redact_headers,
    redact_query_params,
)

SCHEMA_VERSION = "1.0"


# ── Public API ──────────────────────────────────────────────────────────────


def build_report(
    endpoints: list[ApiEndpoint],
    scenarios: list[TestScenario],
    cases: list[TestCase],
    executions: list[ExecutionResult],
    validations: list[ValidationResult],
) -> dict[str, Any]:
    """Build a JSON-serialisable report dict from pipeline results.

    Raises ``ReportError`` on missing ID references (program error).
    """
    # Build lookup dicts
    scenario_by_id: dict[str, TestScenario] = {s.id: s for s in scenarios}
    endpoint_by_id: dict[str, ApiEndpoint] = {e.id: e for e in endpoints}
    case_by_id: dict[str, TestCase] = {c.id: c for c in cases}
    validation_by_case_id: dict[str, ValidationResult] = {
        v.case_id: v for v in validations
    }

    # Validate references
    for case in cases:
        if case.endpoint_id not in endpoint_by_id:
            raise ReportError(f"case.endpoint_id '{case.endpoint_id}' not found in endpoints")
        if case.scenario_id not in scenario_by_id:
            raise ReportError(f"case.scenario_id '{case.scenario_id}' not found in scenarios")
        if case.id not in validation_by_case_id:
            raise ReportError(f"validation for case_id '{case.id}' not found")

    for exec_ in executions:
        if exec_.case_id not in case_by_id:
            raise ReportError(f"execution.case_id '{exec_.case_id}' not found in cases")

    # Build execution lookup and guard missing executions
    execution_by_case_id: dict[str, ExecutionResult] = {
        e.case_id: e for e in executions
    }
    for case in cases:
        if case.id not in execution_by_case_id:
            raise ReportError(f"execution for case_id '{case.id}' not found")

    # Build endpoint → cases grouping (preserve endpoint order)
    endpoint_cases: dict[str, list[TestCase]] = {e.id: [] for e in endpoints}
    for case in cases:
        endpoint_cases[case.endpoint_id].append(case)

    # ── Summary ─────────────────────────────────────────────────────────────
    total_cases = len(cases)
    passed = sum(1 for v in validations if v.passed)
    errors = sum(1 for v in validations if v.severity == "error")
    failed = total_cases - passed - errors
    pass_rate = passed / total_cases if total_cases > 0 else 0.0

    summary = {
        "total_endpoints": len(endpoints),
        "total_scenarios": len(scenarios),
        "total_cases": total_cases,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "pass_rate": pass_rate,
    }

    # ── Endpoint summaries ──────────────────────────────────────────────────
    endpoint_summaries = []
    for ep in endpoints:
        ep_cases = endpoint_cases[ep.id]
        ep_validations = [validation_by_case_id[c.id] for c in ep_cases]
        ep_passed = sum(1 for v in ep_validations if v.passed)
        ep_errors = sum(1 for v in ep_validations if v.severity == "error")
        ep_failed = len(ep_cases) - ep_passed - ep_errors
        endpoint_summaries.append({
            "endpoint_id": ep.id,
            "method": ep.method,
            "path": ep.path,
            "total_cases": len(ep_cases),
            "passed": ep_passed,
            "failed": ep_failed,
            "errors": ep_errors,
        })

    # ── Case results ────────────────────────────────────────────────────────
    case_results = []
    for case in cases:
        scenario = scenario_by_id[case.scenario_id]
        execution = execution_by_case_id.get(case.id)
        validation = validation_by_case_id[case.id]

        case_results.append(_build_case_result(case, scenario, execution, validation))

    return {
        "schema_version": SCHEMA_VERSION,
        "summary": summary,
        "endpoints": endpoint_summaries,
        "cases": case_results,
    }


def write_json_report(report: dict[str, Any], output_path: Path) -> Path:
    """Write *report* to *output_path* as UTF-8 JSON.

    Creates parent directories if they don't exist.  Returns the path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


# ── Internal helpers ────────────────────────────────────────────────────────


def _build_case_result(
    case: TestCase,
    scenario: TestScenario,
    execution: ExecutionResult | None,
    validation: ValidationResult,
) -> dict[str, Any]:
    scenario_info = {
        "source": scenario.source,
        "category": scenario.category,
        "name": scenario.name,
        "target_location": scenario.target_location,
        "target_path": scenario.target_path,
    }

    request_info = {
        "method": case.method,
        "path": case.path,
        "query_params": redact_query_params(case.query_params),
        "path_params": case.path_params,
        "headers": redact_headers(case.headers),
        "cookies": redact_cookies(case.cookies),
        "body": redact_body(case.body),
    }

    if execution is not None:
        execution_info = {
            "status_code": execution.status_code,
            "response_time_ms": execution.response_time_ms,
            "response_headers": redact_headers(execution.response_headers),
            "response_body": redact_body(execution.response_body),
            "error": execution.error,
        }
    else:
        execution_info = {
            "status_code": None,
            "response_time_ms": None,
            "response_headers": {},
            "response_body": None,
            "error": None,
        }

    validation_info = {
        "passed": validation.passed,
        "severity": validation.severity,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "expected": c.expected,
                "actual": c.actual,
                "message": c.message,
            }
            for c in validation.checks
        ],
    }

    return {
        "case_id": case.id,
        "scenario_id": case.scenario_id,
        "endpoint_id": case.endpoint_id,
        "scenario": scenario_info,
        "request": request_info,
        "execution": execution_info,
        "validation": validation_info,
    }
