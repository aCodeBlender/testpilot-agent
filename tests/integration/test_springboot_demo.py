"""T0208 — End-to-End Integration Test against Spring Boot Demo.

Runs the full TestPilot deterministic pipeline against a real Spring Boot
server.  No MockTransport — real HTTP.

Requires Java 17+ and Maven (via wrapper).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from testpilot.openapi import load_openapi, map_to_api_spec
from testpilot.planner import generate_scenarios
from testpilot.generator import generate_test_cases
from testpilot.executor import RequestBuilder, HttpExecutor
from testpilot.validator import validate
from testpilot.report import build_report, write_json_report

# ── Constants ────────────────────────────────────────────────────────────────

SPRING_BOOT_DIR = Path(__file__).resolve().parent.parent.parent / "demo" / "springboot-demo"
READINESS_TIMEOUT = 60  # seconds
READINESS_POLL = 0.5  # seconds between polls


# ── Helpers ──────────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _check_java() -> bool:
    """Return True if Java 17+ is available."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _find_mvn() -> list[str]:
    """Find a working Maven command.

    Priority: mvn on PATH → wrapper cache → mvnw wrapper script.
    """
    # 1. Try mvn on PATH
    maven = shutil.which("mvn")
    if maven:
        return [maven]

    # 2. Try wrapper cache (~/.m2/wrapper/dists/)
    home = Path.home()
    wrapper_cache = home / ".m2" / "wrapper" / "dists"
    if wrapper_cache.exists():
        for cached in wrapper_cache.rglob("mvn.cmd" if sys.platform == "win32" else "mvn"):
            if sys.platform == "win32":
                return ["cmd", "/c", str(cached)]
            return [str(cached)]

    # 3. Fall back to wrapper script
    if sys.platform == "win32":
        mvnw = str(SPRING_BOOT_DIR / "mvnw.cmd")
    else:
        mvnw = str(SPRING_BOOT_DIR / "mvnw")

    if not os.path.exists(mvnw):
        pytest.fail(
            "Neither 'mvn' on PATH nor Maven wrapper found. "
            "Install Maven or ensure demo/springboot-demo/mvnw exists."
        )

    if sys.platform == "win32":
        return ["cmd", "/c", mvnw]
    return [mvnw]


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def springboot_server():
    """Start Spring Boot demo, yield base URL, then tear down."""
    if not _check_java():
        pytest.skip("Java 17+ is required for Spring Boot integration tests")

    mvnw_cmd = _find_mvn()
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Build
    print(f"\n[T0208] Building Spring Boot demo at {SPRING_BOOT_DIR}...")
    build_result = subprocess.run(
        mvnw_cmd + ["package", "-DskipTests", "-q"],
        cwd=str(SPRING_BOOT_DIR),
        capture_output=True, text=True, timeout=120,
    )
    if build_result.returncode != 0:
        pytest.fail(f"Maven build failed:\n{build_result.stderr[-2000:]}")

    # Find the jar
    target_dir = SPRING_BOOT_DIR / "target"
    jars = list(target_dir.glob("*.jar"))
    if not jars:
        pytest.fail(f"No jar found in {target_dir}")
    jar_path = str(jars[0])

    # Start — use PIPE + background drain so we can capture logs on failure
    # WITHOUT risking a full-pipe deadlock when the server writes logs during
    # request processing (the classic subprocess PIPE deadlock).
    print(f"[T0208] Starting Spring Boot on port {port}...")
    _log_lines: list[str] = []
    process = subprocess.Popen(
        ["java", "-jar", jar_path, f"--server.port={port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(SPRING_BOOT_DIR),
    )

    # Drain stdout in background to prevent pipe-buffer deadlock
    def _drain_stdout() -> None:
        try:
            for raw_line in iter(process.stdout.readline, b""):
                _log_lines.append(raw_line.decode("utf-8", errors="replace"))
        except Exception:
            pass

    _drain_thread = threading.Thread(target=_drain_stdout, daemon=True)
    _drain_thread.start()

    # Wait for readiness
    ready = False
    start_time = time.monotonic()
    while time.monotonic() - start_time < READINESS_TIMEOUT:
        try:
            import urllib.request
            req = urllib.request.Request(f"{base_url}/v3/api-docs")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(READINESS_POLL)

    if not ready:
        process.kill()
        logs = "".join(_log_lines)[-3000:] or "(no output captured)"
        pytest.fail(f"Spring Boot did not become ready within {READINESS_TIMEOUT}s.\nLogs:\n{logs}")

    print(f"[T0208] Spring Boot ready at {base_url}")
    yield base_url

    # Teardown
    print(f"\n[T0208] Shutting down Spring Boot (pid={process.pid})...")
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# ── Test ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_full_pipeline(springboot_server: str, tmp_path: Path):
    """Run the full TestPilot pipeline against the live Spring Boot demo."""
    base_url = springboot_server
    openapi_url = f"{base_url}/v3/api-docs"

    # ── A. Load OpenAPI ──────────────────────────────────────────────────
    print(f"\n[T0208] Loading OpenAPI from {openapi_url}...")
    resolved = load_openapi(openapi_url)
    assert isinstance(resolved, dict), "load_openapi should return a dict"
    assert "paths" in resolved, "Resolved spec should have 'paths'"

    # ── B. Map to domain ─────────────────────────────────────────────────
    print("[T0208] Mapping to domain models...")
    api_spec = map_to_api_spec(resolved)
    assert len(api_spec.endpoints) >= 3, f"Expected >= 3 endpoints, got {len(api_spec.endpoints)}"

    # ── C. Find POST /users ──────────────────────────────────────────────
    post_users = None
    for ep in api_spec.endpoints:
        if ep.method == "POST" and ep.path == "/users":
            post_users = ep
            break
    assert post_users is not None, "POST /users endpoint not found"
    print(f"[T0208] Found POST /users (id={post_users.id})")

    # Verify OpenAPI declares 201
    assert "201" in post_users.responses, (
        f"POST /users should declare 201 response, "
        f"got keys: {list(post_users.responses.keys())}"
    )

    # ── D. Generate scenarios ────────────────────────────────────────────
    print("[T0208] Generating scenarios...")
    scenarios = generate_scenarios(post_users, max_cases=20)
    assert len(scenarios) >= 2, f"Expected >= 2 scenarios, got {len(scenarios)}"

    # Find happy_path
    happy_scenario = None
    for sc in scenarios:
        if sc.category == "happy_path":
            happy_scenario = sc
            break
    assert happy_scenario is not None, "happy_path scenario not generated"
    print(f"[T0208] Happy path scenario: id={happy_scenario.id}")

    # Find required_missing body.name
    bug_scenario = None
    for sc in scenarios:
        if (
            sc.category == "required_missing"
            and sc.target_location == "body"
            and sc.target_path == "body.name"
        ):
            bug_scenario = sc
            break
    assert bug_scenario is not None, (
        "required_missing body.name scenario not generated. "
        f"Got: {[(s.category, s.target_location, s.target_path) for s in scenarios]}"
    )
    print(f"[T0208] Bug scenario: id={bug_scenario.id}")

    # ── E. Generate test cases ───────────────────────────────────────────
    print("[T0208] Generating test cases...")
    happy_cases = generate_test_cases(post_users, happy_scenario)
    assert len(happy_cases) >= 1, "No happy path test cases generated"

    bug_cases = generate_test_cases(post_users, bug_scenario)
    assert len(bug_cases) >= 1, "No bug test cases generated"

    happy_case = happy_cases[0]
    bug_case = bug_cases[0]

    # Verify bug case doesn't have name in body
    if isinstance(bug_case.body, dict):
        assert "name" not in bug_case.body, (
            f"Bug case body should not have 'name', got: {bug_case.body}"
        )
    print(f"[T0208] Happy case: id={happy_case.id}")
    print(f"[T0208] Bug case: id={bug_case.id}, body={bug_case.body}")

    # ── F. Build requests ────────────────────────────────────────────────
    builder = RequestBuilder(base_url=base_url)
    happy_request = builder.build(happy_case)
    bug_request = builder.build(bug_case)

    # ── G. Execute HTTP ──────────────────────────────────────────────────
    executor = HttpExecutor(timeout_seconds=30.0)

    print("[T0208] Executing happy path...")
    happy_execution = executor.execute(happy_case, happy_request)
    print(f"[T0208]   -> status={happy_execution.status_code}, error={happy_execution.error}")

    print("[T0208] Executing bug case...")
    bug_execution = executor.execute(bug_case, bug_request)
    print(f"[T0208]   -> status={bug_execution.status_code}, error={bug_execution.error}")

    # ── H. Validate ──────────────────────────────────────────────────────
    print("[T0208] Validating...")
    happy_validation = validate(post_users, happy_scenario, happy_case, happy_execution)
    bug_validation = validate(post_users, bug_scenario, bug_case, bug_execution)

    # ── Assert happy path ────────────────────────────────────────────────
    assert happy_execution.status_code == 201, (
        f"Happy path should return 201, got {happy_execution.status_code}"
    )
    assert happy_validation.passed is True, (
        f"Happy path should pass validation, got: {happy_validation}"
    )
    assert happy_validation.severity == "pass"
    print("[T0208] Happy path: 201, PASS")

    # ── Assert intentional bug ───────────────────────────────────────────
    assert bug_execution.status_code == 500, (
        f"Bug case should return 500, got {bug_execution.status_code}"
    )
    assert bug_execution.error is None, (
        f"Bug case error should be None (HTTP response, not transport error), got: {bug_execution.error}"
    )
    assert bug_validation.passed is False, "Bug case should fail validation"
    assert bug_validation.severity == "fail", (
        f"Bug case severity should be 'fail', got: {bug_validation.severity}"
    )

    # Status check should fail with message about 4xx vs 500
    status_checks = [c for c in bug_validation.checks if c.name == "status"]
    assert len(status_checks) == 1, "Expected exactly one status check"
    status_check = status_checks[0]
    assert status_check.passed is False, "Status check should fail"
    assert "500" in (status_check.actual or ""), (
        f"Status check actual should contain '500', got: {status_check.actual}"
    )
    print("[T0208] Intentional bug: 500, FAIL")

    # ── I. JSON Report ───────────────────────────────────────────────────
    print("[T0208] Building JSON report...")
    report = build_report(
        endpoints=[post_users],
        scenarios=[happy_scenario, bug_scenario],
        cases=[happy_case, bug_case],
        executions=[happy_execution, bug_execution],
        validations=[happy_validation, bug_validation],
    )

    report_path = write_json_report(report, tmp_path / "report.json")
    assert report_path.exists(), "report.json should be written"

    # Verify report summary
    summary = report["summary"]
    assert summary["total_cases"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["errors"] == 0
    assert abs(summary["pass_rate"] - 0.5) < 1e-9

    # Verify bug case in report
    bug_report_case = None
    for c in report["cases"]:
        if c["scenario"]["category"] == "required_missing":
            bug_report_case = c
            break
    assert bug_report_case is not None, "Bug case not found in report"
    assert bug_report_case["scenario"]["target_path"] == "body.name"
    assert bug_report_case["execution"]["status_code"] == 500
    assert bug_report_case["validation"]["passed"] is False
    assert bug_report_case["validation"]["severity"] == "fail"

    print(f"[T0208] * Report written to {report_path}")
    print(f"[T0208]   Summary: {json.dumps(summary, indent=2)}")
    print("[T0208] * ALL INTEGRATION CHECKS PASSED")
