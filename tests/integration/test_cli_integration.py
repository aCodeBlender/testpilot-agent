"""T0209 — CLI Integration Test against Spring Boot Demo.

Runs the CLI (`python -m testpilot run`) against a real Spring Boot server.
No MockTransport — real HTTP.

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
    print(f"\n[T0209-CLI] Building Spring Boot demo at {SPRING_BOOT_DIR}...")
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
    print(f"[T0209-CLI] Starting Spring Boot on port {port}...")
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

    print(f"[T0209-CLI] Spring Boot ready at {base_url}")
    yield base_url

    # Teardown
    print(f"\n[T0209-CLI] Shutting down Spring Boot (pid={process.pid})...")
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# ── Test ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_cli_run(springboot_server: str, tmp_path: Path):
    """Run the CLI against the live Spring Boot demo.

    Verifies:
    1. CLI successfully loads real OpenAPI
    2. CLI executes POST /users and other endpoints
    3. Intentional bug (required_missing body.name) is detected
    4. report.json is generated
    5. Exit code == 1 (test failures detected)
    """
    base_url = springboot_server
    openapi_url = f"{base_url}/v3/api-docs"
    report_path = tmp_path / "report.json"

    # Run the CLI as a subprocess (real end-to-end)
    result = subprocess.run(
        [
            sys.executable, "-m", "testpilot", "run",
            "--openapi", openapi_url,
            "--base-url", base_url,
            "--output", str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    # ── 1. Exit code should be 1 (test failures detected) ────────────────
    print(f"\n[T0209-CLI] Exit code: {result.returncode}")
    print(f"[T0209-CLI] STDOUT:\n{result.stdout[-2000:]}")
    print(f"[T0209-CLI] STDERR:\n{result.stderr[-2000:]}")

    assert result.returncode == 1, (
        f"CLI should exit 1 (test failures), got {result.returncode}.\n"
        f"stdout: {result.stdout[-1000:]}\n"
        f"stderr: {result.stderr[-1000:]}"
    )

    # ── 2. Report should exist ───────────────────────────────────────────
    assert report_path.exists(), f"report.json not found at {report_path}"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report["summary"]

    print(f"\n[T0209-CLI] Report summary: {json.dumps(summary, indent=2)}")

    # ── 3. Should have tested multiple endpoints ─────────────────────────
    assert summary["total_cases"] > 0, "Should have at least one test case"
    assert summary["total_endpoints"] >= 1, "Should have at least one endpoint"

    # ── 4. Should have at least one failure ──────────────────────────────
    assert summary["failed"] >= 1, (
        f"Should have at least 1 failure (intentional bug), "
        f"got: passed={summary['passed']}, failed={summary['failed']}, errors={summary['errors']}"
    )

    # ── 5. Intentional bug: required_missing body.name → 500 → FAIL ─────
    bug_case = None
    for case in report.get("cases", []):
        scenario = case.get("scenario", {})
        if (
            scenario.get("category") == "required_missing"
            and scenario.get("target_path") == "body.name"
        ):
            bug_case = case
            break

    assert bug_case is not None, (
        "Intentional bug case (required_missing body.name) not found in report. "
        f"Categories found: {[c['scenario']['category'] for c in report.get('cases', [])]}"
    )

    assert bug_case["execution"]["status_code"] == 500, (
        f"Intentional bug should return 500, got {bug_case['execution']['status_code']}"
    )
    assert bug_case["validation"]["passed"] is False, "Intentional bug should fail validation"
    assert bug_case["validation"]["severity"] == "fail", (
        f"Intentional bug severity should be 'fail', got {bug_case['validation']['severity']}"
    )

    print(f"[T0209-CLI] Intentional bug detected: "
          f"status={bug_case['execution']['status_code']}, "
          f"passed={bug_case['validation']['passed']}, "
          f"severity={bug_case['validation']['severity']}")

    # ── 6. Console output should show summary ────────────────────────────
    assert "Summary" in result.stderr, "CLI should print summary to stderr"
    assert "Pass rate" in result.stderr, "CLI should show pass rate"

    print(f"\n[T0209-CLI] ALL CLI INTEGRATION CHECKS PASSED")
