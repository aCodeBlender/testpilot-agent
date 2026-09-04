"""Gradio web application for TestPilot.

This module is the only file that imports Gradio.  All execution goes
through the existing ``run_pipeline`` runner — no logic is duplicated.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import gradio as gr

from testpilot.config import AppConfig
from testpilot.llm.config import LLMConfig, load_llm_config_from_env
from testpilot.llm.exceptions import LLMConfigError
from testpilot.runner import RunOutcome, run_pipeline

# ── Defaults (UI convenience only — not baked into runner) ────────────────

_DEFAULT_OPENAPI = "http://localhost:8080/v3/api-docs"
_DEFAULT_BASE_URL = "http://localhost:8080"

# ── Result formatting (pure functions — testable without Gradio) ──────────


def format_summary(outcome: RunOutcome) -> str:
    """Render the top-level summary as Markdown."""
    report = outcome.report
    summary = report.get("summary", {})

    lines = [
        "## Test Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Endpoints | {summary.get('total_endpoints', 0)} |",
        f"| Cases | {summary.get('total_cases', 0)} |",
        f"| Passed | {summary.get('passed', 0)} |",
        f"| Failed | {summary.get('failed', 0)} |",
        f"| Errors | {summary.get('errors', 0)} |",
        f"| Pass rate | {summary.get('pass_rate', 0.0) * 100:.1f}% |",
    ]
    return "\n".join(lines)


def format_case_results(outcome: RunOutcome) -> str:
    """Render individual case results grouped by endpoint as Markdown."""
    report = outcome.report
    cases = report.get("cases", [])
    if not cases:
        return "_No test cases executed._"

    lines: list[str] = []
    current_endpoint: str | None = None

    for case in cases:
        endpoint_label = _endpoint_label(case)

        # Endpoint header
        if endpoint_label != current_endpoint:
            current_endpoint = endpoint_label
            lines.append(f"### {endpoint_label}")
            lines.append("")

        lines.append(_format_single_case(case))
        lines.append("")

    return "\n".join(lines)


def _endpoint_label(case: dict) -> str:
    """Extract 'METHOD /path' from a case dict."""
    method = case.get("request", {}).get("method", "?")
    path = case.get("request", {}).get("path", "?")
    return f"{method} {path}"


def _format_single_case(case: dict) -> str:
    """Format one case as a compact Markdown block."""
    scenario = case.get("scenario", {})
    execution = case.get("execution", {})
    validation = case.get("validation", {})
    request = case.get("request", {})

    # Status
    passed = validation.get("passed", False)
    severity = validation.get("severity", "")
    if execution.get("error") and execution.get("status_code") is None:
        status = "❌ ERROR"
    elif passed:
        status = "✅ PASS"
    else:
        status = "❌ FAIL"

    # Source badge
    source = scenario.get("source", "deterministic")
    if source == "llm":
        source_badge = "🤖 AI"
    else:
        source_badge = "⚙️ Deterministic"

    # Scenario info
    scenario_name = scenario.get("name", scenario.get("category", ""))
    category = scenario.get("category", "")
    target_path = scenario.get("target_path", "")

    # Execution info
    status_code = execution.get("status_code", "—")
    response_time = execution.get("response_time_ms")

    # Validation message
    checks = validation.get("checks", [])
    fail_messages = [c.get("message", "") for c in checks if not c.get("passed", True)]
    fail_detail = fail_messages[0] if fail_messages else ""

    # Build output
    parts = [
        f"**{status}** {source_badge}",
        f"**{scenario_name}** ({category})",
    ]
    if target_path:
        parts.append(f"Target: `{target_path}`")

    time_str = f" · {response_time:.0f}ms" if response_time else ""
    parts.append(f"HTTP {status_code}{time_str}")

    if fail_detail:
        parts.append(f"> {fail_detail}")

    # Request details (collapsible)
    parts.append("")
    parts.append(_format_request_details(request))
    parts.append("")

    # Response details
    parts.append(_format_response_details(execution, validation))

    return "\n".join(parts)


def _format_request_details(request: dict) -> str:
    """Format request details as a collapsible section."""
    method = request.get("method", "?")
    path = request.get("path", "?")
    query = request.get("query_params", {})
    path_params = request.get("path_params", {})
    headers = _redact_headers(request.get("headers", {}))
    body = request.get("body")

    lines = [
        "<details>",
        f"<summary>📤 Request: {method} {path}</summary>",
        "",
    ]

    if query:
        lines.append(f"**Query:** `{json.dumps(query, ensure_ascii=False)}`")
    if path_params:
        lines.append(f"**Path Params:** `{json.dumps(path_params, ensure_ascii=False)}`")
    if headers:
        lines.append(f"**Headers:** `{json.dumps(headers, ensure_ascii=False)}`")
    if body is not None:
        lines.append("**Body:**")
        lines.append("```json")
        lines.append(json.dumps(body, indent=2, ensure_ascii=False))
        lines.append("```")

    lines.append("</details>")
    return "\n".join(lines)


def _format_response_details(
    execution: dict,
    validation: dict,
) -> str:
    """Format response details as a collapsible section."""
    status_code = execution.get("status_code", "—")
    response_time = execution.get("response_time_ms")
    response_body = execution.get("body")
    error = execution.get("error")

    lines = [
        "<details>",
        f"<summary>📥 Response: HTTP {status_code}</summary>",
        "",
    ]

    if response_time:
        lines.append(f"**Time:** {response_time:.0f}ms")

    if error:
        lines.append(f"**Error:** `{error}`")

    if response_body is not None:
        lines.append("**Body:**")
        lines.append("```json")
        if isinstance(response_body, (dict, list)):
            lines.append(json.dumps(response_body, indent=2, ensure_ascii=False))
        else:
            lines.append(str(response_body))
        lines.append("```")

    # Validation checks
    checks = validation.get("checks", [])
    if checks:
        lines.append("**Validation:**")
        for check in checks:
            passed = check.get("passed", False)
            icon = "✅" if passed else "❌"
            msg = check.get("message", "")
            lines.append(f"- {icon} {msg}")

    lines.append("</details>")
    return "\n".join(lines)


def _redact_headers(headers: dict) -> dict:
    """Redact sensitive headers."""
    sensitive = {"authorization", "cookie", "set-cookie", "x-api-key"}
    return {
        k: "***REDACTED***" if k.lower() in sensitive else v
        for k, v in headers.items()
    }


# ── Secret-safe traceback printing ────────────────────────────────────────

# Patterns that look like secret values in exception messages.
# Each pattern matches ``key=value`` or ``key: value`` forms commonly
# produced by libraries and by TestPilot itself.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Bearer bare token: "Bearer sk-xxx" — must come before key=value
    # so that "Authorization: Bearer sk-xxx" redacts the token, not "Bearer".
    re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE),
    # key=value forms: api_key=sk-xxx, token=xxx, secret=xxx
    re.compile(
        r"((?:api[_-]?key|token|secret|password|authorization)"
        r"\s*[=:]\s*)(\S+)",
        re.IGNORECASE,
    ),
    # Common key prefixes: sk-xxx, sk-proj-xxx
    re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b"),
]


def _redact_secrets(text: str) -> str:
    """Replace secret-like values with ``[REDACTED]``."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[REDACTED]"
                           if m.lastindex and m.lastindex >= 2
                           else "[REDACTED]", text)
    return text


def _print_sanitized_traceback() -> None:
    """Print the current traceback to stderr with secret values redacted.

    Preserves exception type, file, line number, and function name.
    Only the exception *message* line is sanitized.
    """
    lines = traceback.format_exception(*sys.exc_info())
    for line in lines:
        sys.stderr.write(_redact_secrets(line))
    sys.stderr.flush()


# ── Runner call ───────────────────────────────────────────────────────────


def run_test(
    openapi_url: str,
    base_url: str,
    goal: str,
) -> tuple[str, str]:
    """Execute a TestPilot run and return (summary_md, details_md).

    This is the function called by the Gradio submit button.
    All execution goes through the existing runner.

    The entire body is wrapped in a single try/except so that:
    - Expected user/config errors produce a clean UI message.
    - Unexpected internal errors print a traceback to the server
      terminal (for the developer) and show a generic message in the
      browser (no secrets or raw internals leaked).
    """
    try:
        openapi_url = openapi_url.strip()
        base_url = base_url.strip()
        goal = goal.strip() or ""

        if not openapi_url:
            return "❌ **Error:** OpenAPI URL is required.", ""
        if not base_url:
            return "❌ **Error:** Target Base URL is required.", ""

        # Build config
        config = AppConfig(
            openapi_source=openapi_url,
            target_base_url=base_url,
            goal=goal or None,
        )

        # Load LLM config only when goal is set
        llm_config: LLMConfig | None = None
        if goal:
            llm_config = load_llm_config_from_env()

        # Run pipeline
        with NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            outcome = run_pipeline(config, Path(tmp.name), llm_config=llm_config)

        # Check for pipeline errors before formatting
        if outcome.exit_code == 2:
            error_msg = outcome.report.get("error", "Unknown error")
            return f"❌ **Error:** {error_msg}", ""

        # Format results
        summary = format_summary(outcome)
        details = format_case_results(outcome)

        return summary, details

    except LLMConfigError as exc:
        return (
            f"❌ **LLM configuration error:** {exc}\n\n"
            "Set the required environment variables or create a `.env` file. "
            "See `.env.example` for reference.",
            "",
        )
    except Exception:
        _print_sanitized_traceback()
        return (
            "❌ Internal TestPilot error. See server console for details.",
            "",
        )


# ── Gradio app factory ────────────────────────────────────────────────────


def create_app() -> gr.Blocks:
    """Create the Gradio Blocks application.

    Returns a ``gr.Blocks`` instance ready to be launched.
    """
    with gr.Blocks(title="TestPilot") as app:
        gr.Markdown("# TestPilot")
        gr.Markdown("REST API testing from OpenAPI specs — deterministic + AI-powered")

        with gr.Row():
            with gr.Column():
                openapi_input = gr.Textbox(
                    label="OpenAPI",
                    placeholder="http://localhost:8080/v3/api-docs",
                    value=_DEFAULT_OPENAPI,
                )
                base_url_input = gr.Textbox(
                    label="Target Base URL",
                    placeholder="http://localhost:8080",
                    value=_DEFAULT_BASE_URL,
                )
                goal_input = gr.Textbox(
                    label="Testing Goal",
                    placeholder="测试用户创建和查询功能，重点检查邮箱格式和字段边界",
                    lines=3,
                )
                run_btn = gr.Button("Run Test", variant="primary")

        with gr.Row():
            with gr.Column():
                summary_output = gr.Markdown(label="Summary")
        with gr.Row():
            with gr.Column():
                details_output = gr.Markdown(label="Test Cases")

        run_btn.click(
            fn=run_test,
            inputs=[openapi_input, base_url_input, goal_input],
            outputs=[summary_output, details_output],
        )

    return app


def launch_app(**kwargs: Any) -> None:
    """Launch the Gradio app.

    Convenience wrapper used by the CLI ``web`` command.
    """
    app = create_app()
    app.launch(show_error=True, **kwargs)
