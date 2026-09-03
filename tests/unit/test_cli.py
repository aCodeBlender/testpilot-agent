"""Unit tests for CLI and Runner — T0209.

Tests use monkeypatch to avoid real HTTP calls and real OpenAPI loading.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from testpilot.cli import app
from testpilot.config import AppConfig
from testpilot.runner import RunOutcome, run_pipeline

runner = CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_report(total=1, passed=1, failed=0, errors=0):
    """Build a minimal valid report dict."""
    pass_rate = passed / total if total > 0 else 0.0
    return {
        "schema_version": "1.0",
        "summary": {
            "total_endpoints": 1,
            "total_scenarios": total,
            "total_cases": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate": pass_rate,
        },
        "endpoints": [],
        "cases": [],
    }


def _mock_run_outcome(exit_code=0, total=1, passed=1, failed=0, errors=0, report_path=None):
    """Create a RunOutcome with the given stats."""
    report = _make_report(total=total, passed=passed, failed=failed, errors=errors)
    return RunOutcome(
        report=report,
        report_path=report_path,
        exit_code=exit_code,
        endpoints_count=1,
        cases_count=total,
        passed_count=passed,
        failed_count=failed,
        errors_count=errors,
    )


# ── CLI Help ─────────────────────────────────────────────────────────────────


class TestCLIHelp:
    """Test CLI help output."""

    def test_run_help(self):
        """python -m testpilot run --help should work."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--openapi" in result.output
        assert "--base-url" in result.output
        assert "--output" in result.output
        assert "--max-cases" in result.output
        assert "--timeout" in result.output
        assert "--include-tag" in result.output
        assert "--exclude-tag" in result.output

    def test_run_help_shows_description(self):
        """Run help should show command description."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "deterministic" in result.output.lower() or "api tests" in result.output.lower()

    def test_missing_required_options(self):
        """Missing --openapi and --base-url should give clear error."""
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0
        # Typer shows error about missing options
        assert "Missing" in result.output or "Error" in result.output or "required" in result.output.lower()

    def test_missing_base_url(self):
        """Missing --base-url should give clear error."""
        result = runner.invoke(app, ["run", "--openapi", "http://example.com/spec"])
        assert result.exit_code != 0

    def test_missing_openapi(self):
        """Missing --openapi should give clear error."""
        result = runner.invoke(app, ["run", "--base-url", "http://example.com"])
        assert result.exit_code != 0


# ── CLI: Run command end-to-end (mocked pipeline) ───────────────────────────


class TestCLIRunCommand:
    """Test the CLI run command with mocked pipeline."""

    def test_successful_run(self, tmp_path: Path):
        """Successful run should show summary and exit 0."""
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_make_report(1, 1, 0, 0)))

        outcome = _mock_run_outcome(exit_code=0, total=1, passed=1, failed=0, report_path=report_path)

        with patch("testpilot.cli.run_pipeline", return_value=outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--output", str(tmp_path / "report.json"),
            ])

        assert result.exit_code == 0
        assert "Summary" in result.output
        assert "1" in result.output  # cases count

    def test_failed_run(self, tmp_path: Path):
        """Run with failures should exit 1."""
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_make_report(2, 1, 1, 0)))

        outcome = _mock_run_outcome(exit_code=1, total=2, passed=1, failed=1, report_path=report_path)

        with patch("testpilot.cli.run_pipeline", return_value=outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--output", str(tmp_path / "report.json"),
            ])

        assert result.exit_code == 1

    def test_error_run(self, tmp_path: Path):
        """Run with application error should exit 2."""
        outcome = RunOutcome(
            exit_code=2,
            report={"error": "No endpoints found in OpenAPI spec."},
        )

        with patch("testpilot.cli.run_pipeline", return_value=outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
            ])

        assert result.exit_code == 2
        assert "No endpoints found" in result.output

    def test_unexpected_exception(self, tmp_path: Path):
        """Unexpected exception should exit 2."""
        with patch("testpilot.cli.run_pipeline", side_effect=RuntimeError("boom")):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
            ])

        assert result.exit_code == 2


# ── CLI: Tags ────────────────────────────────────────────────────────────────


class TestCLITags:
    """Test CLI tag filtering."""

    def test_include_tags(self, tmp_path: Path):
        """--include-tag should be passed to config."""
        outcome = _mock_run_outcome(exit_code=0, report_path=tmp_path / "report.json")

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--include-tag", "users",
                "--include-tag", "admin",
            ])

        assert mock_run.called
        config_arg = mock_run.call_args[0][0]
        assert config_arg.include_tags == ["users", "admin"]

    def test_exclude_tags(self, tmp_path: Path):
        """--exclude-tag should be passed to config."""
        outcome = _mock_run_outcome(exit_code=0, report_path=tmp_path / "report.json")

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--exclude-tag", "internal",
            ])

        assert mock_run.called
        config_arg = mock_run.call_args[0][0]
        assert config_arg.exclude_tags == ["internal"]

    def test_multiple_include_exclude(self, tmp_path: Path):
        """Multiple include and exclude tags."""
        outcome = _mock_run_outcome(exit_code=0, report_path=tmp_path / "report.json")

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--include-tag", "users",
                "--include-tag", "admin",
                "--exclude-tag", "internal",
                "--exclude-tag", "deprecated",
            ])

        config_arg = mock_run.call_args[0][0]
        assert config_arg.include_tags == ["users", "admin"]
        assert config_arg.exclude_tags == ["internal", "deprecated"]


# ── CLI: Output Path ─────────────────────────────────────────────────────────


class TestCLIOutputPath:
    """Test CLI output path handling."""

    def test_custom_output_path(self, tmp_path: Path):
        """--output should be passed to run_pipeline."""
        output_path = tmp_path / "custom" / "report.json"
        outcome = _mock_run_outcome(exit_code=0, report_path=output_path)

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
                "--output", str(output_path),
            ])

        assert mock_run.called
        path_arg = mock_run.call_args[0][1]
        assert path_arg == output_path

    def test_default_output_path(self):
        """Default output should be report.json."""
        outcome = _mock_run_outcome(exit_code=0, report_path=Path("report.json"))

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
            ])

        assert mock_run.called
        path_arg = mock_run.call_args[0][1]
        assert path_arg == Path("report.json")


# ── CLI: Token handling ──────────────────────────────────────────────────────


class TestCLIToken:
    """Test bearer token handling."""

    def test_token_from_env(self, monkeypatch):
        """TESTPILOT_BEARER_TOKEN env var should be read."""
        monkeypatch.setenv("TESTPILOT_BEARER_TOKEN", "my-secret-token")
        outcome = _mock_run_outcome(exit_code=0, report_path=Path("report.json"))

        with patch("testpilot.cli.run_pipeline", return_value=outcome) as mock_run:
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
            ])

        assert mock_run.called
        config_arg = mock_run.call_args[0][0]
        assert config_arg.bearer_token == "my-secret-token"

    def test_token_not_in_console(self, monkeypatch):
        """Token should not appear in console output."""
        monkeypatch.setenv("TESTPILOT_BEARER_TOKEN", "super-secret-123")
        outcome = _mock_run_outcome(exit_code=0, report_path=Path("report.json"))

        with patch("testpilot.cli.run_pipeline", return_value=outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://example.com/spec",
                "--base-url", "http://example.com",
            ])

        # Token should not appear in output
        assert "super-secret-123" not in result.output

    def test_token_not_in_report(self, tmp_path: Path, monkeypatch):
        """Token should not appear in the JSON report."""
        monkeypatch.setenv("TESTPILOT_BEARER_TOKEN", "super-secret-123")

        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
            bearer_token="super-secret-123",
        )

        # Verify that the redaction module would redact auth headers
        from testpilot.report.redact import redact_headers
        headers = {"Authorization": "Bearer super-secret-123", "Content-Type": "application/json"}
        redacted = redact_headers(headers)
        assert redacted["Authorization"] == "[REDACTED]"
        assert redacted["Content-Type"] == "application/json"


# ── Runner: Exit Code 0 (all pass) ──────────────────────────────────────────


class TestRunnerExitCode0:
    """Test runner returns exit_code=0 when all validations pass."""

    def test_all_pass(self, tmp_path: Path):
        """Happy path: all validations pass → exit 0."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_validation = MagicMock()
        mock_validation.passed = True
        mock_validation.severity = "pass"

        mock_report = _make_report(1, 1, 0, 0)

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", return_value=mock_validation),
            patch("testpilot.runner.build_report", return_value=mock_report) as mock_build,
            patch("testpilot.runner.write_json_report") as mock_write,
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenario.category = "happy_path"
            mock_scenarios.return_value = [mock_scenario]

            mock_case = MagicMock()
            mock_case.id = "tc1"
            mock_case.endpoint_id = "ep1"
            mock_case.scenario_id = "sc1"
            mock_cases.return_value = [mock_case]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {"method": "GET", "url": "http://example.com/users", "headers": {}, "params": {}, "cookies": {}, "body": None}
            mock_builder_cls.return_value = mock_builder

            mock_execution = MagicMock()
            mock_execution.case_id = "tc1"
            mock_executor = MagicMock()
            mock_executor.execute.return_value = mock_execution
            mock_executor_cls.return_value = mock_executor

            mock_write.return_value = tmp_path / "report.json"

            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 0
        assert outcome.cases_count == 1
        assert outcome.passed_count == 1
        assert outcome.failed_count == 0


# ── Runner: Exit Code 1 (validation fail) ────────────────────────────────────


class TestRunnerExitCode1:
    """Test runner returns exit_code=1 when any validation fails."""

    def test_validation_fail(self, tmp_path: Path):
        """At least one validation fails → exit 1."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_validation = MagicMock()
        mock_validation.passed = False
        mock_validation.severity = "fail"

        mock_report = _make_report(1, 0, 1, 0)

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", return_value=mock_validation),
            patch("testpilot.runner.build_report", return_value=mock_report),
            patch("testpilot.runner.write_json_report", return_value=tmp_path / "report.json"),
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenarios.return_value = [mock_scenario]

            mock_case = MagicMock()
            mock_case.id = "tc1"
            mock_case.endpoint_id = "ep1"
            mock_case.scenario_id = "sc1"
            mock_cases.return_value = [mock_case]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_builder_cls.return_value = mock_builder

            mock_executor = MagicMock()
            mock_executor.execute.return_value = MagicMock(case_id="tc1")
            mock_executor_cls.return_value = mock_executor

            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 1
        assert outcome.passed_count == 0
        assert outcome.failed_count == 1

    def test_transport_error(self, tmp_path: Path):
        """Transport error (connection refused) → exit 1."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_validation = MagicMock()
        mock_validation.passed = False
        mock_validation.severity = "error"

        mock_report = _make_report(1, 0, 0, 1)

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", return_value=mock_validation),
            patch("testpilot.runner.build_report", return_value=mock_report),
            patch("testpilot.runner.write_json_report", return_value=tmp_path / "report.json"),
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenarios.return_value = [mock_scenario]

            mock_case = MagicMock()
            mock_case.id = "tc1"
            mock_case.endpoint_id = "ep1"
            mock_case.scenario_id = "sc1"
            mock_cases.return_value = [mock_case]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_builder_cls.return_value = mock_builder

            mock_executor = MagicMock()
            mock_executor.execute.return_value = MagicMock(case_id="tc1")
            mock_executor_cls.return_value = mock_executor

            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 1

    def test_mixed_pass_fail(self, tmp_path: Path):
        """Mix of pass and fail → exit 1."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        validation_pass = MagicMock()
        validation_pass.passed = True
        validation_pass.severity = "pass"

        validation_fail = MagicMock()
        validation_fail.passed = False
        validation_fail.severity = "fail"

        mock_report = _make_report(2, 1, 1, 0)

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", side_effect=[validation_pass, validation_fail]),
            patch("testpilot.runner.build_report", return_value=mock_report),
            patch("testpilot.runner.write_json_report", return_value=tmp_path / "report.json"),
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenarios.return_value = [mock_scenario]

            mock_case1 = MagicMock()
            mock_case1.id = "tc1"
            mock_case1.endpoint_id = "ep1"
            mock_case1.scenario_id = "sc1"
            mock_case2 = MagicMock()
            mock_case2.id = "tc2"
            mock_case2.endpoint_id = "ep1"
            mock_case2.scenario_id = "sc1"
            mock_cases.return_value = [mock_case1, mock_case2]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_builder_cls.return_value = mock_builder

            mock_executor = MagicMock()
            mock_executor.execute.return_value = MagicMock(case_id="tc1")
            mock_executor_cls.return_value = mock_executor

            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 1


# ── Runner: Exit Code 2 (application errors) ─────────────────────────────────


class TestRunnerExitCode2:
    """Test runner returns exit_code=2 on application/input errors."""

    def test_loader_error(self, tmp_path: Path):
        """OpenAPI load failure → exit 2."""
        config = AppConfig(
            openapi_source="http://example.com/bad-spec",
            target_base_url="http://example.com",
        )

        with patch("testpilot.runner.load_openapi", side_effect=Exception("Failed to load")):
            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 2
        assert "error" in outcome.report

    def test_no_endpoints(self, tmp_path: Path):
        """No endpoints in spec → exit 2."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[])),
        ):
            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 2
        assert "No endpoints found" in outcome.report.get("error", "")

    def test_selector_empty(self, tmp_path: Path):
        """Filters exclude all endpoints → exit 2."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
            include_tags=["nonexistent"],
        )

        mock_endpoint = MagicMock()
        mock_endpoint.tags = ["users"]

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[mock_endpoint])),
            patch("testpilot.runner.select_endpoints", return_value=[]),
        ):
            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 2
        assert "No endpoints matched" in outcome.report.get("error", "")

    def test_testcase_generator_error(self, tmp_path: Path):
        """TestCaseGeneratorError → exit 2."""
        from testpilot.generator.exceptions import TestCaseGeneratorError

        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_endpoint = MagicMock()
        mock_endpoint.id = "ep1"
        mock_endpoint.method = "POST"
        mock_endpoint.path = "/users"
        mock_endpoint.tags = []

        mock_scenario = MagicMock()
        mock_scenario.id = "sc1"
        mock_scenario.endpoint_id = "ep1"
        mock_scenario.category = "happy_path"

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[mock_endpoint])),
            patch("testpilot.runner.select_endpoints", return_value=[mock_endpoint]),
            patch("testpilot.runner.generate_scenarios", return_value=[mock_scenario]),
            patch("testpilot.runner.generate_test_cases", side_effect=TestCaseGeneratorError("Cannot generate")),
        ):
            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 2
        assert "Cannot generate deterministic test case" in outcome.report.get("error", "")
        assert "POST /users" in outcome.report.get("error", "")

    def test_report_error(self, tmp_path: Path):
        """Report build error → exit 2."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_validation = MagicMock()
        mock_validation.passed = True

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", return_value=mock_validation),
            patch("testpilot.runner.build_report", side_effect=Exception("ReportError")),
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenarios.return_value = [mock_scenario]

            mock_case = MagicMock()
            mock_case.id = "tc1"
            mock_case.endpoint_id = "ep1"
            mock_case.scenario_id = "sc1"
            mock_cases.return_value = [mock_case]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_builder_cls.return_value = mock_builder

            mock_executor = MagicMock()
            mock_executor.execute.return_value = MagicMock(case_id="tc1")
            mock_executor_cls.return_value = mock_executor

            outcome = run_pipeline(config, tmp_path / "report.json")

        assert outcome.exit_code == 2


# ── Runner: No mutation ──────────────────────────────────────────────────────


class TestRunnerNoMutation:
    """Test that runner does not mutate input/domain state."""

    def test_config_not_mutated(self, tmp_path: Path):
        """AppConfig should not be mutated by run_pipeline."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
            include_tags=["users"],
            exclude_tags=["internal"],
        )

        # Store original values
        orig_source = config.openapi_source
        orig_url = config.target_base_url
        orig_include = config.include_tags.copy()
        orig_exclude = config.exclude_tags.copy()

        with patch("testpilot.runner.load_openapi", side_effect=Exception("stop")):
            outcome = run_pipeline(config, tmp_path / "report.json")

        # Config should be unchanged
        assert config.openapi_source == orig_source
        assert config.target_base_url == orig_url
        assert config.include_tags == orig_include
        assert config.exclude_tags == orig_exclude


# ── Runner: Include/Exclude Tags ─────────────────────────────────────────────


class TestRunnerTags:
    """Test runner passes tags to selector correctly."""

    def test_include_tags_passed(self, tmp_path: Path):
        """include_tags should be passed to select_endpoints."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
            include_tags=["users", "admin"],
        )

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[MagicMock()])),
            patch("testpilot.runner.select_endpoints") as mock_select,
        ):
            mock_select.return_value = []  # Will cause exit 2
            run_pipeline(config, tmp_path / "report.json")

            mock_select.assert_called_once()
            call_kwargs = mock_select.call_args
            assert call_kwargs[1]["include_tags"] == ["users", "admin"]

    def test_exclude_tags_passed(self, tmp_path: Path):
        """exclude_tags should be passed to select_endpoints."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
            exclude_tags=["internal"],
        )

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[MagicMock()])),
            patch("testpilot.runner.select_endpoints") as mock_select,
        ):
            mock_select.return_value = []  # Will cause exit 2
            run_pipeline(config, tmp_path / "report.json")

            call_kwargs = mock_select.call_args
            assert call_kwargs[1]["exclude_tags"] == ["internal"]

    def test_empty_tags_passed_as_none(self, tmp_path: Path):
        """Empty tag lists should be passed as None to select_endpoints."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec", return_value=MagicMock(endpoints=[MagicMock()])),
            patch("testpilot.runner.select_endpoints") as mock_select,
        ):
            mock_select.return_value = []
            run_pipeline(config, tmp_path / "report.json")

            call_kwargs = mock_select.call_args
            assert call_kwargs[1]["include_tags"] is None
            assert call_kwargs[1]["exclude_tags"] is None


# ── Runner: Report Generated ─────────────────────────────────────────────────


class TestRunnerReport:
    """Test that report is generated correctly."""

    def test_report_file_created(self, tmp_path: Path):
        """Report file should be created on success."""
        config = AppConfig(
            openapi_source="http://example.com/spec",
            target_base_url="http://example.com",
        )

        mock_validation = MagicMock()
        mock_validation.passed = True
        mock_validation.severity = "pass"

        mock_report = _make_report(1, 1, 0, 0)
        output_path = tmp_path / "subdir" / "report.json"

        with (
            patch("testpilot.runner.load_openapi", return_value={"openapi": "3.0.0"}),
            patch("testpilot.runner.map_to_api_spec") as mock_map,
            patch("testpilot.runner.select_endpoints") as mock_select,
            patch("testpilot.runner.generate_scenarios") as mock_scenarios,
            patch("testpilot.runner.generate_test_cases") as mock_cases,
            patch("testpilot.runner.RequestBuilder") as mock_builder_cls,
            patch("testpilot.runner.HttpExecutor") as mock_executor_cls,
            patch("testpilot.runner.validate", return_value=mock_validation),
            patch("testpilot.runner.build_report", return_value=mock_report),
            patch("testpilot.runner.write_json_report") as mock_write,
        ):
            mock_endpoint = MagicMock()
            mock_endpoint.id = "ep1"
            mock_endpoint.tags = []
            mock_map.return_value = MagicMock(endpoints=[mock_endpoint])
            mock_select.return_value = [mock_endpoint]

            mock_scenario = MagicMock()
            mock_scenario.id = "sc1"
            mock_scenario.endpoint_id = "ep1"
            mock_scenarios.return_value = [mock_scenario]

            mock_case = MagicMock()
            mock_case.id = "tc1"
            mock_case.endpoint_id = "ep1"
            mock_case.scenario_id = "sc1"
            mock_cases.return_value = [mock_case]

            mock_builder = MagicMock()
            mock_builder.build.return_value = {}
            mock_builder_cls.return_value = mock_builder

            mock_executor = MagicMock()
            mock_executor.execute.return_value = MagicMock(case_id="tc1")
            mock_executor_cls.return_value = mock_executor

            mock_write.return_value = output_path

            outcome = run_pipeline(config, output_path)

        assert outcome.exit_code == 0
        assert outcome.report_path == output_path
        mock_write.assert_called_once_with(mock_report, output_path)


# ── CLI --goal tests (T0303) ────────────────────────────────────────────────


class TestCLIGoal:
    """Tests for --goal CLI option."""

    def _set_all_llm_env(self, monkeypatch):
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-test")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://api.test.com/v1")
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "test-model")

    def _clear_all_llm_env(self, monkeypatch):
        monkeypatch.delenv("TESTPILOT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("TESTPILOT_LLM_BASE_URL", raising=False)
        monkeypatch.delenv("TESTPILOT_LLM_MODEL", raising=False)

    def test_no_goal_old_behavior_unchanged(self, monkeypatch):
        """Without --goal, behavior is identical to Phase 2."""
        self._clear_all_llm_env(monkeypatch)
        monkeypatch.delenv("TESTPILOT_BEARER_TOKEN", raising=False)

        mock_outcome = _mock_run_outcome(exit_code=0, total=1, passed=1)

        with patch("testpilot.cli.run_pipeline", return_value=mock_outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://localhost:8080/v3/api-docs",
                "--base-url", "http://localhost:8080",
            ])

        assert result.exit_code == 0

    def test_goal_missing_api_key_exit_2(self, monkeypatch):
        """--goal without TESTPILOT_LLM_API_KEY → exit 2."""
        self._clear_all_llm_env(monkeypatch)

        result = runner.invoke(app, [
            "run",
            "--openapi", "http://localhost:8080/v3/api-docs",
            "--base-url", "http://localhost:8080",
            "--goal", "test everything",
        ])

        assert result.exit_code == 2
        assert "TESTPILOT_LLM_API_KEY" in result.output

    def test_goal_missing_base_url_exit_2(self, monkeypatch):
        """--goal without TESTPILOT_LLM_BASE_URL → exit 2."""
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-test")
        monkeypatch.delenv("TESTPILOT_LLM_BASE_URL", raising=False)
        monkeypatch.setenv("TESTPILOT_LLM_MODEL", "m")

        result = runner.invoke(app, [
            "run",
            "--openapi", "http://localhost:8080/v3/api-docs",
            "--base-url", "http://localhost:8080",
            "--goal", "test everything",
        ])

        assert result.exit_code == 2
        assert "TESTPILOT_LLM_BASE_URL" in result.output

    def test_goal_missing_model_exit_2(self, monkeypatch):
        """--goal without TESTPILOT_LLM_MODEL → exit 2."""
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-test")
        monkeypatch.setenv("TESTPILOT_LLM_BASE_URL", "https://api.test.com/v1")
        monkeypatch.delenv("TESTPILOT_LLM_MODEL", raising=False)

        result = runner.invoke(app, [
            "run",
            "--openapi", "http://localhost:8080/v3/api-docs",
            "--base-url", "http://localhost:8080",
            "--goal", "test everything",
        ])

        assert result.exit_code == 2
        assert "TESTPILOT_LLM_MODEL" in result.output

    def test_goal_with_valid_config(self, monkeypatch):
        """--goal with valid LLM config → pipeline runs."""
        self._set_all_llm_env(monkeypatch)
        mock_outcome = _mock_run_outcome(exit_code=0, total=1, passed=1)
        mock_outcome.intent = MagicMock()
        mock_outcome.intent.selection_mode = "all"
        mock_outcome.intent.excluded_methods = []

        with patch("testpilot.cli.run_pipeline", return_value=mock_outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://localhost:8080/v3/api-docs",
                "--base-url", "http://localhost:8080",
                "--goal", "test everything",
            ])

        assert result.exit_code == 0

    def test_goal_intent_displayed(self, monkeypatch):
        """--goal output shows intent info."""
        self._set_all_llm_env(monkeypatch)
        mock_outcome = _mock_run_outcome(exit_code=0, total=1, passed=1)
        mock_outcome.intent = MagicMock()
        mock_outcome.intent.selection_mode = "subset"
        mock_outcome.intent.excluded_methods = ["DELETE"]

        with patch("testpilot.cli.run_pipeline", return_value=mock_outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://localhost:8080/v3/api-docs",
                "--base-url", "http://localhost:8080",
                "--goal", "test create and get, skip DELETE",
            ])

        assert result.exit_code == 0
        assert "Intent" in result.output

    def test_goal_secret_not_in_output(self, monkeypatch):
        """API key must never appear in CLI output."""
        self._set_all_llm_env(monkeypatch)
        monkeypatch.setenv("TESTPILOT_LLM_API_KEY", "sk-super-secret-key-12345")

        mock_outcome = _mock_run_outcome(exit_code=0, total=1, passed=1)
        mock_outcome.intent = MagicMock()
        mock_outcome.intent.selection_mode = "all"
        mock_outcome.intent.excluded_methods = []

        with patch("testpilot.cli.run_pipeline", return_value=mock_outcome):
            result = runner.invoke(app, [
                "run",
                "--openapi", "http://localhost:8080/v3/api-docs",
                "--base-url", "http://localhost:8080",
                "--goal", "test everything",
            ])

        assert "sk-super-secret-key-12345" not in result.output
