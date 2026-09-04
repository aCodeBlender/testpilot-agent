"""Tests for the TestPilot Web UI — Phase 3C Batch 1.

Tests the result-formatting logic and the runner-calling interface.
All tests use mocks — no real HTTP, LLM, or Gradio server.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from testpilot.runner import RunOutcome
from testpilot.web.app import (
    _redact_headers,
    format_case_results,
    format_summary,
    run_test,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_outcome(
    *,
    total_endpoints: int = 2,
    total_cases: int = 3,
    passed: int = 2,
    failed: int = 1,
    errors: int = 0,
    pass_rate: float = 2 / 3,
    cases: list[dict] | None = None,
) -> RunOutcome:
    """Build a minimal RunOutcome for testing."""
    if cases is None:
        cases = [
            _make_case_result(
                method="POST",
                path="/users",
                scenario_name="Happy path",
                source="deterministic",
                category="happy_path",
                status_code=201,
                passed=True,
            ),
            _make_case_result(
                method="POST",
                path="/users",
                scenario_name="Invalid email",
                source="llm",
                category="semantic_negative",
                target_path="body.email",
                status_code=201,
                passed=False,
                fail_message="Expected 4xx, got 201",
            ),
            _make_case_result(
                method="GET",
                path="/users/1",
                scenario_name="Get user",
                source="deterministic",
                category="happy_path",
                status_code=200,
                passed=True,
            ),
        ]

    report = {
        "summary": {
            "total_endpoints": total_endpoints,
            "total_scenarios": total_cases,
            "total_cases": total_cases,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate": pass_rate,
        },
        "endpoints": [],
        "cases": cases,
    }
    return RunOutcome(
        report=report,
        exit_code=1 if failed > 0 else 0,
        endpoints_count=total_endpoints,
        cases_count=total_cases,
        passed_count=passed,
        failed_count=failed,
        errors_count=errors,
    )


def _make_case_result(
    *,
    method: str = "POST",
    path: str = "/users",
    scenario_name: str = "Happy path",
    source: str = "deterministic",
    category: str = "happy_path",
    target_path: str = "",
    status_code: int = 200,
    response_time_ms: float = 42.5,
    passed: bool = True,
    fail_message: str = "",
    body: dict | None = None,
    headers: dict | None = None,
    query_params: dict | None = None,
    error: str | None = None,
) -> dict:
    """Build a single case result dict matching report format."""
    request: dict = {
        "method": method,
        "path": path,
    }
    if headers:
        request["headers"] = headers
    if query_params:
        request["query_params"] = query_params
    if body is not None:
        request["body"] = body

    execution: dict = {
        "status_code": status_code,
        "response_time_ms": response_time_ms,
    }
    if error:
        execution["error"] = error

    scenario: dict = {
        "name": scenario_name,
        "source": source,
        "category": category,
    }
    if target_path:
        scenario["target_path"] = target_path

    checks = []
    if not passed and fail_message:
        checks.append({"passed": False, "message": fail_message})
    elif passed:
        checks.append({"passed": True, "message": "OK"})

    return {
        "case_id": f"tc-{method.lower()}-{path.replace('/', '-')}-1",
        "endpoint_id": f"ep-{method.lower()}-{path.replace('/', '-')}",
        "scenario": scenario,
        "request": request,
        "execution": execution,
        "validation": {
            "passed": passed,
            "severity": "pass" if passed else "fail",
            "checks": checks,
        },
    }


# ── format_summary ────────────────────────────────────────────────────────


class TestFormatSummary:
    """Test summary formatting."""

    def test_summary_contains_totals(self):
        outcome = _make_outcome(total_endpoints=3, total_cases=10, passed=7, failed=3)
        md = format_summary(outcome)
        assert "| Endpoints | 3 |" in md
        assert "| Cases | 10 |" in md
        assert "| Passed | 7 |" in md
        assert "| Failed | 3 |" in md

    def test_summary_pass_rate(self):
        outcome = _make_outcome(pass_rate=0.75)
        md = format_summary(outcome)
        assert "75.0%" in md

    def test_summary_zero_cases(self):
        outcome = _make_outcome(total_cases=0, passed=0, failed=0, pass_rate=0.0)
        md = format_summary(outcome)
        assert "| Cases | 0 |" in md


# ── format_case_results ───────────────────────────────────────────────────


class TestFormatCaseResults:
    """Test case result formatting."""

    def test_deterministic_source_badge(self):
        outcome = _make_outcome(cases=[
            _make_case_result(source="deterministic"),
        ])
        md = format_case_results(outcome)
        assert "Deterministic" in md

    def test_llm_source_badge(self):
        outcome = _make_outcome(cases=[
            _make_case_result(source="llm"),
        ])
        md = format_case_results(outcome)
        assert "AI" in md

    def test_pass_status(self):
        outcome = _make_outcome(cases=[
            _make_case_result(passed=True),
        ])
        md = format_case_results(outcome)
        assert "PASS" in md

    def test_fail_status(self):
        outcome = _make_outcome(cases=[
            _make_case_result(passed=False, fail_message="bad"),
        ])
        md = format_case_results(outcome)
        assert "FAIL" in md

    def test_error_status(self):
        outcome = _make_outcome(cases=[
            _make_case_result(error="connection refused", status_code=None),
        ])
        md = format_case_results(outcome)
        assert "ERROR" in md

    def test_endpoint_headers(self):
        outcome = _make_outcome(cases=[
            _make_case_result(method="POST", path="/users"),
            _make_case_result(method="GET", path="/items"),
        ])
        md = format_case_results(outcome)
        assert "### POST /users" in md
        assert "### GET /items" in md

    def test_scenario_name_shown(self):
        outcome = _make_outcome(cases=[
            _make_case_result(scenario_name="Invalid email format"),
        ])
        md = format_case_results(outcome)
        assert "Invalid email format" in md

    def test_target_path_shown(self):
        outcome = _make_outcome(cases=[
            _make_case_result(target_path="body.email"),
        ])
        md = format_case_results(outcome)
        assert "body.email" in md

    def test_fail_message_shown(self):
        outcome = _make_outcome(cases=[
            _make_case_result(passed=False, fail_message="Expected 4xx, got 201"),
        ])
        md = format_case_results(outcome)
        assert "Expected 4xx, got 201" in md

    def test_request_body_visible(self):
        outcome = _make_outcome(cases=[
            _make_case_result(body={"email": "not-an-email"}),
        ])
        md = format_case_results(outcome)
        assert "not-an-email" in md

    def test_empty_cases(self):
        outcome = _make_outcome(cases=[])
        md = format_case_results(outcome)
        assert "No test cases" in md


# ── Secret redaction ──────────────────────────────────────────────────────


class TestRedaction:
    """Test that sensitive headers are redacted."""

    def test_authorization_redacted(self):
        result = _redact_headers({"Authorization": "Bearer sk-secret-123"})
        assert result["Authorization"] == "***REDACTED***"

    def test_cookie_redacted(self):
        result = _redact_headers({"Cookie": "session=abc123"})
        assert result["Cookie"] == "***REDACTED***"

    def test_normal_headers_preserved(self):
        result = _redact_headers({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"

    def test_redaction_in_rendered_output(self):
        outcome = _make_outcome(cases=[
            _make_case_result(headers={"Authorization": "Bearer sk-secret"}),
        ])
        md = format_case_results(outcome)
        assert "sk-secret" not in md
        assert "REDACTED" in md


# ── run_test ──────────────────────────────────────────────────────────────


class TestRunTest:
    """Test the run_test function that bridges UI to runner."""

    @patch("testpilot.web.app.run_pipeline")
    def test_calls_runner_with_correct_config(self, mock_run):
        """run_test should pass inputs to the existing runner."""
        mock_run.return_value = _make_outcome()

        run_test("http://localhost:8080/v3/api-docs", "http://localhost:8080", "")

        call_args = mock_run.call_args
        config = call_args[0][0]
        assert config.openapi_source == "http://localhost:8080/v3/api-docs"
        assert config.target_base_url == "http://localhost:8080"
        assert config.goal is None

    @patch("testpilot.web.app.run_pipeline")
    def test_goal_passed_to_runner(self, mock_run):
        """Goal should be passed through to AppConfig."""
        mock_run.return_value = _make_outcome()

        with patch("testpilot.web.app.load_llm_config_from_env") as mock_llm:
            mock_llm.return_value = MagicMock()
            run_test("http://localhost:8080/v3/api-docs", "http://localhost:8080", "test email")

        call_args = mock_run.call_args
        config = call_args[0][0]
        assert config.goal == "test email"

    @patch("testpilot.web.app.run_pipeline")
    def test_empty_goal_no_llm_config(self, mock_run):
        """Empty goal should not require LLM config."""
        mock_run.return_value = _make_outcome()

        summary, details = run_test("http://localhost:8080/v3/api-docs", "http://localhost:8080", "")

        # Should succeed without LLM config
        assert "Error" not in summary or "Test Results" in summary
        mock_run.assert_called_once()

    @patch("testpilot.web.app.run_pipeline")
    def test_missing_openapi_shows_error(self, mock_run):
        """Empty OpenAPI URL should show a clean error."""
        summary, details = run_test("", "http://localhost:8080", "")
        assert "Error" in summary
        assert "OpenAPI" in summary
        mock_run.assert_not_called()

    @patch("testpilot.web.app.run_pipeline")
    def test_missing_base_url_shows_error(self, mock_run):
        """Empty base URL should show a clean error."""
        summary, details = run_test("http://localhost:8080/v3/api-docs", "", "")
        assert "Error" in summary
        assert "Base URL" in summary
        mock_run.assert_not_called()

    @patch("testpilot.web.app.run_pipeline")
    @patch("testpilot.web.app.load_llm_config_from_env")
    def test_missing_llm_config_shows_error(self, mock_llm, mock_run):
        """Missing LLM config with goal should show a clean error."""
        from testpilot.llm.exceptions import LLMConfigError

        mock_llm.side_effect = LLMConfigError("Missing TESTPILOT_LLM_API_KEY")

        summary, details = run_test(
            "http://localhost:8080/v3/api-docs",
            "http://localhost:8080",
            "test something",
        )
        assert "LLM configuration error" in summary
        assert ".env" in summary
        mock_run.assert_not_called()

    @patch("testpilot.web.app.run_pipeline")
    def test_runner_returns_results(self, mock_run):
        """Successful run should return formatted summary and details."""
        mock_run.return_value = _make_outcome()

        summary, details = run_test(
            "http://localhost:8080/v3/api-docs",
            "http://localhost:8080",
            "",
        )
        assert "Test Results" in summary
        assert "Endpoints" in summary

    @patch("testpilot.web.app.run_pipeline")
    def test_runner_exit_code_2_shows_error(self, mock_run):
        """Runner exit_code=2 should show error message."""
        mock_run.return_value = RunOutcome(
            exit_code=2,
            report={"error": "No endpoints found in OpenAPI spec."},
        )

        summary, details = run_test(
            "http://localhost:8080/v3/api-docs",
            "http://localhost:8080",
            "",
        )
        assert "Error" in summary
        assert "No endpoints found" in summary


class TestSemanticVisibility:
    """Test that semantic test details are visible in output."""

    def test_semantic_request_body_shown(self):
        """Mutated request body from semantic test should be visible."""
        outcome = _make_outcome(cases=[
            _make_case_result(
                source="llm",
                body={"email": "not-an-email", "age": 151},
            ),
        ])
        md = format_case_results(outcome)
        assert "not-an-email" in md
        assert "151" in md

    def test_semantic_source_distinct(self):
        """Semantic and deterministic sources should be visually distinct."""
        outcome = _make_outcome(cases=[
            _make_case_result(source="deterministic", scenario_name="Happy"),
            _make_case_result(source="llm", scenario_name="Bad email"),
        ])
        md = format_case_results(outcome)
        assert "Deterministic" in md
        assert "AI" in md

    def test_unexpected_error_shows_generic_message(self):
        """Unexpected exceptions from runner show generic UI message."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError("internal bug")

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )
            assert "Internal TestPilot error" in summary
            assert "server console" in summary
            # Raw exception must NOT leak to the browser
            assert "internal bug" not in summary


# ── Diagnostic regression tests (Phase 3C Batch 1) ────────────────────────


class TestDiagnosticVisibility:
    """Test that unexpected failures are observable in the server terminal."""

    def test_traceback_printed_on_unexpected_runner_error(self, capsys):
        """When run_pipeline raises, traceback must appear on stderr."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError("internal bug")

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err
        assert "internal bug" in captured.err

    def test_traceback_printed_on_formatting_error(self, capsys):
        """When format_summary raises, traceback must appear on stderr."""
        outcome = _make_outcome()
        # Inject bad data: pass_rate as a string will cause
        # TypeError in format_summary ("can't multiply sequence by int")
        outcome.report["summary"]["pass_rate"] = "not-a-number"

        with (
            patch("testpilot.web.app.run_pipeline") as mock_run,
            patch("testpilot.web.app.format_summary") as mock_fmt,
        ):
            mock_run.return_value = outcome
            mock_fmt.side_effect = TypeError("bad format")

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        assert "Internal TestPilot error" in summary

        captured = capsys.readouterr()
        assert "TypeError" in captured.err
        assert "bad format" in captured.err

    def test_formatting_error_not_silently_swallowed(self):
        """Formatting errors must not be silently converted to success."""
        outcome = _make_outcome()
        outcome.report["summary"]["pass_rate"] = "not-a-number"

        with (
            patch("testpilot.web.app.run_pipeline") as mock_run,
            patch("testpilot.web.app.format_summary") as mock_fmt,
        ):
            mock_run.return_value = outcome
            mock_fmt.side_effect = TypeError("bad format")

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        # Must show error, not an empty success
        assert "error" in summary.lower() or "Error" in summary
        assert details == ""

    def test_secrets_not_in_generic_error_message(self):
        """The generic error message must not leak API keys or tokens."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "connection failed with api_key=sk-secret-12345"
            )

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        # The generic message should not contain the exception detail
        assert "sk-secret-12345" not in summary
        assert "api_key" not in summary

    def test_exit_code_2_before_formatting(self):
        """Exit code 2 errors should be returned without calling format functions."""
        with (
            patch("testpilot.web.app.run_pipeline") as mock_run,
            patch("testpilot.web.app.format_summary") as mock_fmt,
            patch("testpilot.web.app.format_case_results") as mock_cases,
        ):
            mock_run.return_value = RunOutcome(
                exit_code=2,
                report={"error": "No endpoints found in OpenAPI spec."},
            )

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        assert "No endpoints found" in summary
        # format functions should NOT have been called
        mock_fmt.assert_not_called()
        mock_cases.assert_not_called()


# ── Secret-safe traceback tests ───────────────────────────────────────────


class TestSanitizedTraceback:
    """Test that terminal tracebacks never leak secrets."""

    def test_api_key_redacted_from_stderr(self, capsys):
        """Fake API key in exception message must not appear on stderr."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "connection failed with api_key=sk-secret-12345"
            )

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        assert "sk-secret-12345" not in captured.err

    def test_bearer_token_redacted_from_stderr(self, capsys):
        """Fake Bearer token in exception message must not appear on stderr."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "auth failed: Authorization: Bearer test-secret-token-abc"
            )

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        assert "test-secret-token-abc" not in captured.err

    def test_exception_type_still_visible_on_stderr(self, capsys):
        """Exception type must remain visible after redaction."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "api_key=sk-fake-key-for-testing-only"
            )

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err

    def test_stack_frames_visible_on_stderr(self, capsys):
        """File paths and line numbers must remain visible after redaction."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "token=secret-value-12345"
            )

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        # Stack frames should contain file references
        assert "test_web.py" in captured.err or "web" in captured.err

    def test_browser_still_generic_on_secret_exception(self):
        """Browser must show generic message, not raw exception with secret."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError(
                "api_key=sk-super-secret-99999"
            )

            summary, details = run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        assert "Internal TestPilot error" in summary
        assert "sk-super-secret-99999" not in summary
        assert "api_key" not in summary

    def test_normal_exception_unredacted_on_stderr(self, capsys):
        """Non-secret exception messages must pass through unchanged."""
        with patch("testpilot.web.app.run_pipeline") as mock_run:
            mock_run.side_effect = ValueError("bad format in spec")

            run_test(
                "http://localhost:8080/v3/api-docs",
                "http://localhost:8080",
                "",
            )

        captured = capsys.readouterr()
        assert "ValueError" in captured.err
        assert "bad format in spec" in captured.err
