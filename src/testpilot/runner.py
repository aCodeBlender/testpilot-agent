"""Runner — thin orchestration for the TestPilot pipeline.

Runs: Load → Map → Select → [optional LLM Intent] → Scenarios → Cases → Build → Execute → Validate → Report.

This is a plain function, not a framework.  CLI decides display and exit codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from testpilot.config import AppConfig
from testpilot.domain.intent import TestIntent
from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.testing import (
    ExecutionResult,
    TestCase,
    TestScenario,
    ValidationResult,
)
from testpilot.executor import HttpExecutor, RequestBuilder
from testpilot.generator import generate_test_cases
from testpilot.generator.exceptions import TestCaseGeneratorError
from testpilot.llm.client import OpenAICompatibleLLMClient
from testpilot.llm.config import LLMConfig
from testpilot.openapi import load_openapi, map_to_api_spec, select_endpoints
from testpilot.planner import (
    build_endpoint_catalog,
    build_semantic_test_cases,
    generate_scenarios,
    plan_intent,
    plan_semantic_scenarios,
)
from testpilot.planner.intent_exceptions import IntentPlannerError
from testpilot.planner.semantic_eligibility import analyze_execution_eligibility
from testpilot.planner.semantic_exceptions import SemanticPlannerError
from testpilot.report import build_report, write_json_report
from testpilot.validator import validate


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
    intent: TestIntent | None = None


# ── Public API ───────────────────────────────────────────────────────────────


def run_pipeline(
    config: AppConfig,
    output_path: Path,
    *,
    llm_config: LLMConfig | None = None,
) -> RunOutcome:
    """Execute the full TestPilot deterministic pipeline.

    Parameters
    ----------
    config:
        Runtime configuration (openapi source, base URL, filters, limits).
    output_path:
        Where to write the JSON report.
    llm_config:
        Optional LLM configuration.  Only provided when ``config.goal`` is set.
        Not part of AppConfig — loaded separately by the CLI.

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

    # ── C. Select endpoints (deterministic pre-filter) ──────────────────
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

    # ── C2. LLM Intent Planning (optional) ──────────────────────────────
    intent: TestIntent | None = None
    if config.goal:
        if llm_config is None:
            return RunOutcome(
                exit_code=2,
                report={"error": "LLM configuration required when --goal is used."},
            )
        try:
            llm_client = OpenAICompatibleLLMClient(llm_config)
            catalog = build_endpoint_catalog(selected)
            intent = plan_intent(config.goal, catalog, llm_client)
        except IntentPlannerError as exc:
            return RunOutcome(
                exit_code=2,
                report={"error": f"Intent planning failed: {exc}"},
            )
        except Exception as exc:
            return RunOutcome(
                exit_code=2,
                report={"error": f"Unexpected intent planning error: {exc}"},
            )

        # Apply intent to filter endpoints
        if intent.selection_mode == "none":
            return RunOutcome(
                exit_code=0,
                report={
                    "summary": {
                        "total_endpoints": 0,
                        "total_scenarios": 0,
                        "total_cases": 0,
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "pass_rate": 0.0,
                    },
                    "endpoints": [],
                    "cases": [],
                },
                intent=intent,
            )

        selected = select_endpoints(
            selected,
            endpoint_ids=intent.selected_endpoint_ids,
            exclude_methods=intent.excluded_methods or None,
        )

        if not selected:
            return RunOutcome(
                exit_code=0,
                report={
                    "summary": {
                        "total_endpoints": 0,
                        "total_scenarios": 0,
                        "total_cases": 0,
                        "passed": 0,
                        "failed": 0,
                        "errors": 0,
                        "pass_rate": 0.0,
                    },
                    "endpoints": [],
                    "cases": [],
                },
                intent=intent,
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

    # LLM client for semantic planning (only when --goal is set)
    llm_client: OpenAICompatibleLLMClient | None = None
    if llm_config is not None:
        llm_client = OpenAICompatibleLLMClient(llm_config)

    # Track seen scenario IDs for uniqueness across deterministic + semantic
    seen_scenario_ids: set[str] = set()

    for endpoint in selected:
        all_endpoints.append(endpoint)

        # D. Generate deterministic scenarios
        scenarios = generate_scenarios(endpoint, max_cases=config.max_cases_per_endpoint)

        for scenario in scenarios:
            seen_scenario_ids.add(scenario.id)
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

        # ── Semantic planning (only when --goal is set) ─────────────────
        if llm_client is not None:
            try:
                proposals = plan_semantic_scenarios(endpoint, llm_client)
                decisions = analyze_execution_eligibility(proposals, endpoint)

                for decision in decisions:
                    if not decision.eligible:
                        continue  # silently skip non-executable proposals

                    semantic_pairs = build_semantic_test_cases(
                        decision, endpoint, seen_ids=seen_scenario_ids,
                    )
                    for sem_scenario, sem_case in semantic_pairs:
                        all_scenarios.append(sem_scenario)
                        all_cases.append(sem_case)

                        request_data = builder.build(sem_case)
                        execution = executor.execute(sem_case, request_data)
                        all_executions.append(execution)

                        validation = validate(
                            endpoint, sem_scenario, sem_case, execution,
                        )
                        all_validations.append(validation)
            except SemanticPlannerError:
                pass  # expected LLM/planner failures don't abort the run

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
        intent=intent,
    )
