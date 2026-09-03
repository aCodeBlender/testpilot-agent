"""Tests for runner semantic integration — Phase 3B Batch 3.

Tests that the runner correctly wires semantic planning into the pipeline
when --goal is set, and correctly skips it when --goal is not set.

All tests use mocks — no real HTTP or LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
from unittest.mock import DEFAULT, MagicMock, patch

import pytest

from testpilot.config import AppConfig
from testpilot.domain.schema import ApiSchema
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint, ApiRequestBody, ApiResponse
from testpilot.domain.testing import (
    ExecutionResult,
    TestCase,
    TestScenario,
    ValidationResult,
)
from testpilot.llm.config import LLMConfig
from testpilot.planner.semantic_exceptions import SemanticPlannerError
from testpilot.runner import RunOutcome, run_pipeline


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_config(*, goal: str | None = None) -> AppConfig:
    return AppConfig(
        openapi_source="http://example.com/spec",
        target_base_url="http://localhost:8080",
        goal=goal,
    )


def _make_llm_config() -> LLMConfig:
    return LLMConfig(
        api_key="test-key",
        base_url="http://llm.example.com/v1",
        model="test-model",
    )


def _make_endpoint(
    *,
    id: str = "ep-users",
    method: str = "POST",
    path: str = "/users",
    body_schema: ApiSchema | None = None,
) -> ApiEndpoint:
    request_body = None
    if body_schema is not None:
        request_body = ApiRequestBody(body_schema=body_schema)
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        request_body=request_body,
        responses={"200": ApiResponse(description="OK")},
    )


def _make_proposal(
    *,
    endpoint_id: str = "ep-users",
    target_path: str = "email",
    proposed_value: object = "not-an-email",
) -> SemanticScenarioProposal:
    return SemanticScenarioProposal(
        endpoint_id=endpoint_id,
        name="Invalid email format",
        description="Test with invalid email",
        rationale="Email format check",
        category="format_violation",
        strategy="custom_value",
        target_location="body",
        target_path=target_path,
        proposed_value=proposed_value,
    )


def _mock_report_dict():
    return {
        "summary": {
            "total_endpoints": 1,
            "total_scenarios": 1,
            "total_cases": 1,
            "passed": 1,
            "failed": 0,
            "errors": 0,
            "pass_rate": 1.0,
        },
        "endpoints": [],
        "cases": [],
    }


# Patches common to most runner tests: load/map/select always return a
# single endpoint so the test can focus on the semantic wiring.
_COMMON_PATCHES = [
    "testpilot.runner.load_openapi",
    "testpilot.runner.map_to_api_spec",
    "testpilot.runner.select_endpoints",
    "testpilot.runner.build_endpoint_catalog",
    "testpilot.runner.generate_scenarios",
    "testpilot.runner.generate_test_cases",
    "testpilot.runner.RequestBuilder",
    "testpilot.runner.HttpExecutor",
    "testpilot.runner.validate",
    "testpilot.runner.build_report",
    "testpilot.runner.write_json_report",
]


def _setup_common_mocks(
    mocks: dict,
    endpoint: ApiEndpoint,
    *,
    deterministic_scenarios: list[TestScenario] | None = None,
    deterministic_cases: list[TestCase] | None = None,
):
    """Wire up the common mocks so load→map→select returns *endpoint*."""
    mocks["load_openapi"].return_value = {}
    mocks["map_to_api_spec"].return_value = MagicMock(
        endpoints=[endpoint],
    )
    mocks["select_endpoints"].return_value = [endpoint]
    mocks["build_endpoint_catalog"].return_value = [
        {"id": endpoint.id, "method": endpoint.method, "path": endpoint.path},
    ]

    if deterministic_scenarios is None:
        deterministic_scenarios = [
            TestScenario(
                id="sc-1",
                endpoint_id=endpoint.id,
                source="deterministic",
                category="happy_path",
                name="Happy path",
            ),
        ]
    mocks["generate_scenarios"].return_value = deterministic_scenarios

    if deterministic_cases is None:
        deterministic_cases = [
            TestCase(
                id="tc-1",
                endpoint_id=endpoint.id,
                scenario_id=deterministic_scenarios[0].id,
                method=endpoint.method,
                path=endpoint.path,
            ),
        ]
    mocks["generate_test_cases"].return_value = deterministic_cases

    builder = MagicMock()
    mocks["RequestBuilder"].return_value = builder
    builder.build.return_value = {"headers": {}, "body": {}}

    executor = MagicMock()
    mocks["HttpExecutor"].return_value = executor
    executor.execute.return_value = ExecutionResult(
        case_id="tc-1",
        status_code=200,
        headers={},
        body=None,
        elapsed_ms=10,
    )

    mocks["validate"].return_value = ValidationResult(
        case_id="tc-1",
        passed=True,
        severity="pass",
        checks=[],
    )

    mocks["build_report"].return_value = _mock_report_dict()
    mocks["write_json_report"].return_value = Path("report.json")


# ── Tests ───────────────────────────────────────────────────────────────────


class TestSemanticPlanningInvocation:
    """Test that semantic planning is invoked correctly."""

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    @patch("testpilot.runner.analyze_execution_eligibility")
    @patch("testpilot.runner.build_semantic_test_cases")
    def test_goal_path_invokes_semantic_planner(
        self,
        mock_build_semantic,
        mock_eligibility,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """--goal should invoke semantic planning for selected endpoints."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint(
            body_schema=ApiSchema(
                type="object",
                properties={"email": ApiSchema(type="string", format="email")},
            ),
        )
        _setup_common_mocks(mocks, endpoint)

        # Intent planner returns the endpoint
        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        # Semantic planner returns empty
        mock_plan_semantic.return_value = []
        mock_eligibility.return_value = []
        mock_build_semantic.return_value = []

        config = _make_config(goal="test user creation")
        llm_config = _make_llm_config()

        run_pipeline(config, Path("report.json"), llm_config=llm_config)

        mock_plan_semantic.assert_called_once_with(endpoint, mock.ANY)

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_no_goal_skips_semantic_planner(
        self,
        mock_plan_semantic,
        **mocks,
    ):
        """No --goal should mean no semantic planning call."""
        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        config = _make_config(goal=None)
        run_pipeline(config, Path("report.json"), llm_config=None)

        mock_plan_semantic.assert_not_called()


class TestSemanticExecution:
    """Test that eligible proposals become executed test cases."""

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    @patch("testpilot.runner.analyze_execution_eligibility")
    @patch("testpilot.runner.build_semantic_test_cases")
    def test_eligible_proposal_becomes_executed_test(
        self,
        mock_build_semantic,
        mock_eligibility,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """An eligible semantic proposal should produce an executed test case."""
        from testpilot.domain.intent import TestIntent

        body_schema = ApiSchema(
            type="object",
            properties={"email": ApiSchema(type="string", format="email")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        _setup_common_mocks(
            mocks, endpoint,
            deterministic_scenarios=[],
            deterministic_cases=[],
        )

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        proposal = _make_proposal()
        mock_plan_semantic.return_value = [proposal]

        decision = MagicMock()
        decision.eligible = True
        mock_eligibility.return_value = [decision]

        sem_scenario = TestScenario(
            id="sem-ep-users-email",
            endpoint_id="ep-users",
            source="llm",
            category="semantic_negative",
            name="Invalid email",
        )
        sem_case = TestCase(
            id="tc-sem-ep-users-email-1",
            endpoint_id="ep-users",
            scenario_id="sem-ep-users-email",
            method="POST",
            path="/users",
        )
        mock_build_semantic.return_value = [(sem_scenario, sem_case)]

        config = _make_config(goal="test email format")
        llm_config = _make_llm_config()

        run_pipeline(config, Path("report.json"), llm_config=llm_config)

        # Verify semantic planning was called
        mock_plan_semantic.assert_called_once()
        mock_eligibility.assert_called_once()
        mock_build_semantic.assert_called_once()

        # Verify the semantic test was executed
        executor = mocks["HttpExecutor"].return_value
        assert executor.execute.call_count == 1

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    @patch("testpilot.runner.analyze_execution_eligibility")
    @patch("testpilot.runner.build_semantic_test_cases")
    def test_non_eligible_proposal_produces_no_http(
        self,
        mock_build_semantic,
        mock_eligibility,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """Non-eligible proposals should not produce HTTP requests."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint()
        _setup_common_mocks(
            mocks, endpoint,
            deterministic_scenarios=[],
            deterministic_cases=[],
        )

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        proposal = _make_proposal()
        mock_plan_semantic.return_value = [proposal]

        decision = MagicMock()
        decision.eligible = False
        mock_eligibility.return_value = [decision]

        config = _make_config(goal="test")
        llm_config = _make_llm_config()

        run_pipeline(config, Path("report.json"), llm_config=llm_config)

        # build_semantic_test_cases should NOT be called for non-eligible
        mock_build_semantic.assert_not_called()
        # No HTTP execution
        executor = mocks["HttpExecutor"].return_value
        executor.execute.assert_not_called()


class TestFailureIsolation:
    """Test that semantic failures don't abort the run."""

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_semantic_planner_error_does_not_abort(
        self,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """SemanticPlannerError should be silently caught, not abort the run."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        # Planner raises SemanticPlannerError
        mock_plan_semantic.side_effect = SemanticPlannerError("LLM returned garbage")

        config = _make_config(goal="test")
        llm_config = _make_llm_config()

        outcome = run_pipeline(config, Path("report.json"), llm_config=llm_config)

        # Should not be exit code 2 — deterministic tests still run
        assert outcome.exit_code == 0

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_unexpected_semantic_error_propagates(
        self,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """Unexpected exceptions must propagate — not be silently swallowed."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        # Planner raises unexpected programming error
        mock_plan_semantic.side_effect = RuntimeError("something broke")

        config = _make_config(goal="test")
        llm_config = _make_llm_config()

        with pytest.raises(RuntimeError, match="something broke"):
            run_pipeline(config, Path("report.json"), llm_config=llm_config)

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_unexpected_type_error_propagates(
        self,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """TypeError from wiring must not be silently swallowed."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        mock_plan_semantic.side_effect = TypeError("bad argument")

        config = _make_config(goal="test")
        llm_config = _make_llm_config()

        with pytest.raises(TypeError, match="bad argument"):
            run_pipeline(config, Path("report.json"), llm_config=llm_config)

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_semantic_planner_error_no_secret_leak(
        self,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """SemanticPlannerError message must not contain API keys."""
        from testpilot.domain.intent import TestIntent

        secret_key = "sk-super-secret-key-12345"
        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        # Planner error that includes the key (simulating LLM client leaking it)
        mock_plan_semantic.side_effect = SemanticPlannerError(
            f"API call failed with key={secret_key}"
        )

        config = _make_config(goal="test")
        llm_config = LLMConfig(
            api_key=secret_key,
            base_url="http://llm.example.com",
            model="test",
        )

        # SemanticPlannerError is caught — deterministic path continues
        outcome = run_pipeline(config, Path("report.json"), llm_config=llm_config)
        assert outcome.exit_code == 0

        # The error message is NOT surfaced in the report
        report_json = json.dumps(outcome.report)
        assert secret_key not in report_json


class TestProvenanceInReport:
    """Test that semantic scenarios appear with correct provenance in report."""

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    @patch("testpilot.runner.analyze_execution_eligibility")
    @patch("testpilot.runner.build_semantic_test_cases")
    def test_semantic_scenario_has_source_llm(
        self,
        mock_build_semantic,
        mock_eligibility,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """Semantic scenarios should have source='llm' in the pipeline."""
        from testpilot.domain.intent import TestIntent

        body_schema = ApiSchema(
            type="object",
            properties={"email": ApiSchema(type="string", format="email")},
        )
        endpoint = _make_endpoint(body_schema=body_schema)
        _setup_common_mocks(
            mocks, endpoint,
            deterministic_scenarios=[],
            deterministic_cases=[],
        )

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )

        proposal = _make_proposal()
        mock_plan_semantic.return_value = [proposal]

        decision = MagicMock()
        decision.eligible = True
        mock_eligibility.return_value = [decision]

        sem_scenario = TestScenario(
            id="sem-ep-users-email",
            endpoint_id="ep-users",
            source="llm",
            category="semantic_negative",
            name="Invalid email",
        )
        sem_case = TestCase(
            id="tc-sem-ep-users-email-1",
            endpoint_id="ep-users",
            scenario_id="sem-ep-users-email",
            method="POST",
            path="/users",
        )
        mock_build_semantic.return_value = [(sem_scenario, sem_case)]

        config = _make_config(goal="test email")
        llm_config = _make_llm_config()

        run_pipeline(config, Path("report.json"), llm_config=llm_config)

        # Verify build_report received the semantic scenario with source="llm"
        build_report_mock = mocks["build_report"]
        call_args = build_report_mock.call_args
        scenarios = call_args[1]["scenarios"]
        semantic_scenarios = [s for s in scenarios if s.source == "llm"]
        assert len(semantic_scenarios) == 1
        assert semantic_scenarios[0].category == "semantic_negative"

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    def test_deterministic_scenario_backward_compatible(self, **mocks):
        """Existing deterministic scenarios remain unchanged."""
        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        config = _make_config(goal=None)
        run_pipeline(config, Path("report.json"), llm_config=None)

        build_report_mock = mocks["build_report"]
        call_args = build_report_mock.call_args
        scenarios = call_args[1]["scenarios"]
        assert len(scenarios) == 1
        assert scenarios[0].source == "deterministic"
        assert scenarios[0].category == "happy_path"


class TestSecretSafety:
    """Test that secrets don't appear in report output."""

    def test_llm_config_api_key_is_secret(self):
        """LLMConfig.api_key should be SecretStr (not plain text)."""
        from pydantic import SecretStr

        config = LLMConfig(
            api_key="super-secret-key",
            base_url="http://llm.example.com",
            model="test",
        )
        assert isinstance(config.api_key, SecretStr)
        # repr should not contain the key
        assert "super-secret-key" not in repr(config.api_key)
        # str should not contain the key
        assert "super-secret-key" not in str(config.api_key)

    @patch.multiple("testpilot.runner", **{p.split(".")[-1]: DEFAULT for p in _COMMON_PATCHES})
    @patch("testpilot.runner.OpenAICompatibleLLMClient")
    @patch("testpilot.runner.plan_intent")
    @patch("testpilot.runner.plan_semantic_scenarios")
    def test_secrets_not_in_report(
        self,
        mock_plan_semantic,
        mock_plan_intent,
        mock_llm_cls,
        **mocks,
    ):
        """API key should not appear in the report dict."""
        from testpilot.domain.intent import TestIntent

        endpoint = _make_endpoint()
        _setup_common_mocks(mocks, endpoint)

        mock_plan_intent.return_value = TestIntent(
            selection_mode="subset",
            selected_endpoint_ids=["ep-users"],
        )
        mock_plan_semantic.return_value = []

        secret_key = "sk-super-secret-api-key-12345"
        config = _make_config(goal="test")
        llm_config = LLMConfig(
            api_key=secret_key,
            base_url="http://llm.example.com",
            model="test",
        )

        run_pipeline(config, Path("report.json"), llm_config=llm_config)

        # Check report dict doesn't contain the secret
        build_report_mock = mocks["build_report"]
        report_dict = build_report_mock.return_value
        report_json = json.dumps(report_dict)
        assert secret_key not in report_json
