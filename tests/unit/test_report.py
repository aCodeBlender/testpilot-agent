"""Tests for T0206: JSON Report."""

import json
import tempfile
from pathlib import Path

import pytest

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiResponse
from testpilot.domain.testing import (
    CheckResult,
    ExecutionResult,
    TestCase,
    TestScenario,
    ValidationResult,
)
from testpilot.report import build_report, write_json_report, ReportError
from testpilot.report.redact import (
    redact_body,
    redact_cookies,
    redact_headers,
    redact_query_params,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(id: str = "ep-1", method: str = "GET", path: str = "/test") -> ApiEndpoint:
    return ApiEndpoint(id=id, path=path, method=method, responses={})


def _scenario(
    id: str = "sc-1",
    endpoint_id: str = "ep-1",
    category: str = "happy_path",
    name: str = "Happy path",
    source: str = "deterministic",
    target_location=None,
    target_path=None,
) -> TestScenario:
    return TestScenario(
        id=id,
        endpoint_id=endpoint_id,
        source=source,
        category=category,
        name=name,
        target_location=target_location,
        target_path=target_path,
    )


def _case(
    id: str = "tc-1",
    endpoint_id: str = "ep-1",
    scenario_id: str = "sc-1",
    method: str = "GET",
    path: str = "/test",
    headers: dict | None = None,
    query_params: dict | None = None,
    path_params: dict | None = None,
    cookies: dict | None = None,
    body=None,
) -> TestCase:
    return TestCase(
        id=id,
        endpoint_id=endpoint_id,
        scenario_id=scenario_id,
        method=method,
        path=path,
        headers=headers or {},
        query_params=query_params or {},
        path_params=path_params or {},
        cookies=cookies or {},
        body=body,
    )


def _execution(
    case_id: str = "tc-1",
    status_code: int | None = 200,
    response_body=None,
    response_body_present: bool | None = None,
    response_time_ms: float = 10.0,
    response_headers: dict | None = None,
    error: str | None = None,
) -> ExecutionResult:
    if response_body_present is None:
        response_body_present = response_body is not None
    return ExecutionResult(
        case_id=case_id,
        status_code=status_code,
        response_headers=response_headers or {},
        response_body=response_body,
        response_body_present=response_body_present,
        response_time_ms=response_time_ms,
        error=error,
    )


def _validation(
    case_id: str = "tc-1",
    passed: bool = True,
    severity: str = "pass",
    checks: list[CheckResult] | None = None,
) -> ValidationResult:
    return ValidationResult(
        case_id=case_id,
        passed=passed,
        severity=severity,
        checks=checks or [CheckResult(name="status", passed=True)],
    )


def _build_simple_report(
    endpoints=None,
    scenarios=None,
    cases=None,
    executions=None,
    validations=None,
):
    eps = endpoints or [_endpoint()]
    scs = scenarios or [_scenario()]
    tcs = cases or [_case()]
    exs = executions or [_execution()]
    vls = validations or [_validation()]
    return build_report(eps, scs, tcs, exs, vls)


# ── Summary ──────────────────────────────────────────────────────────────────


class TestSummary:
    def test_all_pass(self):
        report = _build_simple_report()
        s = report["summary"]
        assert s["total_cases"] == 1
        assert s["passed"] == 1
        assert s["failed"] == 0
        assert s["errors"] == 0
        assert s["pass_rate"] == 1.0

    def test_pass_fail_error_mixed(self):
        cases = [_case(id="tc-1"), _case(id="tc-2"), _case(id="tc-3")]
        validations = [
            _validation(case_id="tc-1", passed=True, severity="pass"),
            _validation(case_id="tc-2", passed=False, severity="fail"),
            _validation(case_id="tc-3", passed=False, severity="error"),
        ]
        executions = [_execution(case_id=c.id) for c in cases]
        report = _build_simple_report(cases=cases, executions=executions, validations=validations)
        s = report["summary"]
        assert s["total_cases"] == 3
        assert s["passed"] == 1
        assert s["failed"] == 1
        assert s["errors"] == 1
        assert abs(s["pass_rate"] - 1 / 3) < 1e-9

    def test_pass_rate_zero_cases(self):
        report = build_report([_endpoint()], [_scenario()], [], [], [])
        assert report["summary"]["pass_rate"] == 0.0
        assert report["summary"]["total_cases"] == 0

    def test_schema_version(self):
        report = _build_simple_report()
        assert report["schema_version"] == "1.0"


# ── Endpoint summary ─────────────────────────────────────────────────────────


class TestEndpointSummary:
    def test_multi_endpoint_grouping(self):
        eps = [_endpoint(id="ep-1", path="/a"), _endpoint(id="ep-2", path="/b")]
        scs = [_scenario(id="sc-1", endpoint_id="ep-1"), _scenario(id="sc-2", endpoint_id="ep-2")]
        tcs = [
            _case(id="tc-1", endpoint_id="ep-1", scenario_id="sc-1"),
            _case(id="tc-2", endpoint_id="ep-1", scenario_id="sc-1"),
            _case(id="tc-3", endpoint_id="ep-2", scenario_id="sc-2"),
        ]
        exs = [_execution(case_id=c.id) for c in tcs]
        vls = [
            _validation(case_id="tc-1", passed=True),
            _validation(case_id="tc-2", passed=False, severity="fail"),
            _validation(case_id="tc-3", passed=True),
        ]
        report = build_report(eps, scs, tcs, exs, vls)
        ep_summaries = report["endpoints"]
        assert len(ep_summaries) == 2
        assert ep_summaries[0]["endpoint_id"] == "ep-1"
        assert ep_summaries[0]["total_cases"] == 2
        assert ep_summaries[0]["passed"] == 1
        assert ep_summaries[0]["failed"] == 1
        assert ep_summaries[1]["endpoint_id"] == "ep-2"
        assert ep_summaries[1]["total_cases"] == 1
        assert ep_summaries[1]["passed"] == 1

    def test_endpoint_order_stable(self):
        """Same input → same endpoint order."""
        eps = [_endpoint(id="ep-x"), _endpoint(id="ep-y")]
        scs = [_scenario(id="sc-x", endpoint_id="ep-x"), _scenario(id="sc-y", endpoint_id="ep-y")]
        tcs = [_case(id="tc-x", endpoint_id="ep-x", scenario_id="sc-x")]
        exs = [_execution(case_id="tc-x")]
        vls = [_validation(case_id="tc-x")]
        r1 = build_report(eps, scs, tcs, exs, vls)
        r2 = build_report(eps, scs, tcs, exs, vls)
        assert [e["endpoint_id"] for e in r1["endpoints"]] == [e["endpoint_id"] for e in r2["endpoints"]]


# ── Case result ──────────────────────────────────────────────────────────────


class TestCaseResult:
    def test_scenario_info(self):
        sc = _scenario(category="required_missing", name="Missing name",
                       target_location="body", target_path="body.name")
        report = _build_simple_report(scenarios=[sc])
        c = report["cases"][0]
        assert c["scenario"]["source"] == "deterministic"
        assert c["scenario"]["category"] == "required_missing"
        assert c["scenario"]["name"] == "Missing name"
        assert c["scenario"]["target_location"] == "body"
        assert c["scenario"]["target_path"] == "body.name"

    def test_scenario_source_llm(self):
        """LLM-sourced scenarios must show source='llm' in report."""
        sc = _scenario(category="semantic_negative", name="Bad email",
                       source="llm", target_location="body",
                       target_path="body.email")
        report = _build_simple_report(scenarios=[sc])
        c = report["cases"][0]
        assert c["scenario"]["source"] == "llm"
        assert c["scenario"]["category"] == "semantic_negative"

    def test_request_info(self):
        tc = _case(
            method="POST", path="/users",
            headers={"Content-Type": "application/json"},
            query_params={"v": "1"},
            path_params={"id": "42"},
            body={"name": "Alice"},
        )
        report = _build_simple_report(cases=[tc])
        req = report["cases"][0]["request"]
        assert req["method"] == "POST"
        assert req["path"] == "/users"
        assert req["query_params"] == {"v": "1"}
        assert req["path_params"] == {"id": "42"}
        assert req["body"] == {"name": "Alice"}

    def test_execution_info(self):
        ex = _execution(
            status_code=200,
            response_time_ms=42.5,
            response_headers={"Content-Type": "application/json"},
            response_body={"id": 1},
        )
        report = _build_simple_report(executions=[ex])
        ei = report["cases"][0]["execution"]
        assert ei["status_code"] == 200
        assert ei["response_time_ms"] == 42.5
        assert ei["response_body"] == {"id": 1}
        assert ei["error"] is None

    def test_validation_checks(self):
        checks = [
            CheckResult(name="status", passed=True, expected="200", actual="200", message=None),
            CheckResult(name="schema", passed=False, expected="object", actual="null", message="wrong type"),
        ]
        val = _validation(passed=False, severity="fail", checks=checks)
        report = _build_simple_report(validations=[val])
        vi = report["cases"][0]["validation"]
        assert vi["passed"] is False
        assert vi["severity"] == "fail"
        assert len(vi["checks"]) == 2
        assert vi["checks"][0]["name"] == "status"
        assert vi["checks"][1]["message"] == "wrong type"

    def test_execution_missing_raises(self):
        """No execution for a case → ReportError."""
        with pytest.raises(ReportError, match="execution for case_id"):
            build_report(
                [_endpoint()], [_scenario()], [_case()], [], [_validation()],
            )


# ── Redaction ────────────────────────────────────────────────────────────────


class TestRedaction:
    def test_authorization_header(self):
        h = {"Authorization": "Bearer abc123", "Content-Type": "application/json"}
        r = redact_headers(h)
        assert r["Authorization"] == "[REDACTED]"
        assert r["Content-Type"] == "application/json"

    def test_authorization_lowercase(self):
        h = {"authorization": "Bearer abc123"}
        r = redact_headers(h)
        assert r["authorization"] == "[REDACTED]"

    def test_cookie_header(self):
        h = {"Cookie": "session=abc; token=xyz"}
        r = redact_headers(h)
        assert r["Cookie"] == "[REDACTED]"

    def test_set_cookie_header(self):
        h = {"Set-Cookie": "session=abc"}
        r = redact_headers(h)
        assert r["Set-Cookie"] == "[REDACTED]"

    def test_testcase_cookies(self):
        c = {"session": "abc", "refreshToken": "xyz"}
        r = redact_cookies(c)
        assert r["session"] == "[REDACTED]"
        assert r["refreshToken"] == "[REDACTED]"

    def test_token_query(self):
        q = {"token": "abc", "page": "1"}
        r = redact_query_params(q)
        assert r["token"] == "[REDACTED]"
        assert r["page"] == "1"

    def test_nested_password_body(self):
        body = {"user": {"name": "Tom", "password": "123456"}}
        r = redact_body(body)
        assert r["user"]["name"] == "Tom"
        assert r["user"]["password"] == "[REDACTED]"

    def test_response_body_token(self):
        body = {"access_token": "secret123", "data": "ok"}
        r = redact_body(body)
        assert r["access_token"] == "[REDACTED]"
        assert r["data"] == "ok"

    def test_list_nested_secret(self):
        body = [{"secret": "s1", "name": "a"}, {"api_key": "k1"}]
        r = redact_body(body)
        assert r[0]["secret"] == "[REDACTED]"
        assert r[0]["name"] == "a"
        assert r[1]["api_key"] == "[REDACTED]"

    def test_non_sensitive_not_redacted(self):
        body = {"name": "Alice", "age": 30, "email": "a@b.com"}
        r = redact_body(body)
        assert r == body

    def test_no_mutation(self):
        """Redaction must not mutate the original dict."""
        original = {"Authorization": "Bearer secret", "Content-Type": "json"}
        redact_headers(original)
        assert original["Authorization"] == "Bearer secret"

    def test_no_mutation_cookies(self):
        original = {"session": "abc"}
        redact_cookies(original)
        assert original["session"] == "abc"

    def test_no_mutation_body(self):
        original = {"password": "123", "name": "Alice"}
        redact_body(original)
        assert original["password"] == "123"


# ── File output ──────────────────────────────────────────────────────────────


class TestFileOutput:
    def test_json_file_written(self, tmp_path):
        report = _build_simple_report()
        out = write_json_report(report, tmp_path / "report.json")
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["schema_version"] == "1.0"

    def test_utf8_chinese(self, tmp_path):
        sc = _scenario(name="测试中文")
        report = _build_simple_report(scenarios=[sc])
        out = write_json_report(report, tmp_path / "report.json")
        text = out.read_text(encoding="utf-8")
        assert "测试中文" in text
        assert "\\u" not in text

    def test_parent_dir_created(self, tmp_path):
        report = _build_simple_report()
        out = write_json_report(report, tmp_path / "sub" / "dir" / "report.json")
        assert out.exists()

    def test_json_loadable(self, tmp_path):
        report = _build_simple_report()
        out = write_json_report(report, tmp_path / "report.json")
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        assert "cases" in loaded


# ── Guards ───────────────────────────────────────────────────────────────────


class TestGuards:
    def test_missing_endpoint_ref(self):
        tc = _case(endpoint_id="ep-missing")
        with pytest.raises(ReportError, match="ep-missing"):
            build_report([_endpoint()], [_scenario()], [tc], [_execution()], [_validation()])

    def test_missing_scenario_ref(self):
        tc = _case(scenario_id="sc-missing")
        with pytest.raises(ReportError, match="sc-missing"):
            build_report([_endpoint()], [_scenario()], [tc], [_execution()], [_validation()])

    def test_missing_validation_ref(self):
        tc = _case(id="tc-orphan")
        ex = _execution(case_id="tc-orphan")
        with pytest.raises(ReportError, match="tc-orphan"):
            build_report([_endpoint()], [_scenario()], [tc], [ex], [])

    def test_missing_execution_ref(self):
        tc = _case(id="tc-no-exec")
        with pytest.raises(ReportError, match="tc-no-exec"):
            build_report([_endpoint()], [_scenario()], [tc], [], [_validation(case_id="tc-no-exec")])


# ── Determinism ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        """build_report called twice with same data → identical result."""
        r1 = _build_simple_report()
        r2 = _build_simple_report()
        assert r1 == r2
