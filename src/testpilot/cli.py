"""CLI entry point for TestPilot — T0209.

Usage:
    python -m testpilot run --openapi <url-or-path> --base-url <url>
    testpilot run --openapi <url-or-path> --base-url <url>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from testpilot.config import AppConfig
from testpilot.runner import run_pipeline

app = typer.Typer(
    name="testpilot",
    help="TestPilot — Deterministic REST API Testing from OpenAPI specs.",
    no_args_is_help=True,
)


@app.callback()
def _main() -> None:
    """TestPilot — Deterministic REST API Testing from OpenAPI specs."""
    pass

console = Console(stderr=True)


# ── Run command ──────────────────────────────────────────────────────────────


@app.command()
def run(
    openapi: str = typer.Option(
        ...,
        help="OpenAPI spec source: URL (http://...) or local YAML/JSON file path.",
    ),
    base_url: str = typer.Option(
        ...,
        help="Target API base URL (e.g. http://localhost:8080).",
    ),
    output: Path = typer.Option(
        Path("report.json"),
        "--output",
        "-o",
        help="Path for the JSON report output.",
    ),
    max_cases: int | None = typer.Option(
        None,
        "--max-cases",
        help="Max test cases per endpoint (default: 20).",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="HTTP request timeout in seconds (default: 30).",
    ),
    include_tag: list[str] = typer.Option(
        [],
        "--include-tag",
        help="Only test endpoints with these tags (repeatable).",
    ),
    exclude_tag: list[str] = typer.Option(
        [],
        "--exclude-tag",
        help="Skip endpoints with these tags (repeatable).",
    ),
) -> None:
    """Run deterministic API tests against the target."""
    # ── Banner ───────────────────────────────────────────────────────────
    console.print("[bold]TestPilot[/bold] v0.1.0")
    console.print(f"  OpenAPI:  {openapi}")
    console.print(f"  Target:   {base_url}")
    console.print()

    # ── Auth from environment ────────────────────────────────────────────
    bearer_token = os.environ.get("TESTPILOT_BEARER_TOKEN")

    # ── Build config ─────────────────────────────────────────────────────
    try:
        config = AppConfig(
            openapi_source=openapi,
            target_base_url=base_url,
            bearer_token=bearer_token,
            include_tags=include_tag,
            exclude_tags=exclude_tag,
            max_cases_per_endpoint=max_cases or 20,
            timeout_seconds=timeout or 30,
        )
    except Exception as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2)

    # ── Run pipeline ─────────────────────────────────────────────────────
    try:
        outcome = run_pipeline(config, output)
    except Exception as exc:
        console.print(f"[red]Unexpected error:[/red] {exc}")
        raise typer.Exit(code=2)

    # ── Display results ──────────────────────────────────────────────────
    report = outcome.report

    # Check for pipeline errors (exit_code=2)
    if outcome.exit_code == 2:
        error_msg = report.get("error", "Unknown error")
        console.print(f"[red]Error:[/red] {error_msg}")
        raise typer.Exit(code=2)

    # Display per-case results
    _print_case_results(report)

    # Display summary
    _print_summary(outcome)

    # Exit with appropriate code
    raise typer.Exit(code=outcome.exit_code)


# ── Display helpers ──────────────────────────────────────────────────────────


def _print_case_results(report: dict) -> None:
    """Print a compact per-case status table."""
    cases = report.get("cases", [])
    if not cases:
        return

    # Group by endpoint for display
    current_endpoint = None
    for case_result in cases:
        endpoint_id = case_result.get("endpoint_id", "")
        scenario = case_result.get("scenario", {})
        execution = case_result.get("execution", {})
        validation = case_result.get("validation", {})

        method = case_result.get("request", {}).get("method", "")
        path = case_result.get("request", {}).get("path", "")
        endpoint_label = f"{method} {path}"

        # Print endpoint header if changed
        if endpoint_label != current_endpoint:
            console.print(f"\n[bold]{endpoint_label}[/bold]")
            current_endpoint = endpoint_label

        # Status
        category = scenario.get("category", "")
        target = scenario.get("target_path", "")
        status_code = execution.get("status_code")
        response_time = execution.get("response_time_ms")
        passed = validation.get("passed", False)
        severity = validation.get("severity", "")

        # Format status line
        if execution.get("error") and status_code is None:
            # Transport error
            status_str = "[red]ERROR[/red]"
            detail = execution.get("error", "")
            time_str = ""
        elif passed:
            status_str = "[green]PASS[/green]"
            detail = ""
            time_str = f"{response_time:.0f} ms" if response_time else ""
        else:
            status_str = "[red]FAIL[/red]"
            # Get failure message from checks
            checks = validation.get("checks", [])
            fail_messages = [
                c.get("message", "")
                for c in checks
                if not c.get("passed", True)
            ]
            detail = fail_messages[0] if fail_messages else ""
            time_str = f"{response_time:.0f} ms" if response_time else ""

        # Build line
        parts = [f"  {status_str}"]
        if category:
            parts.append(f"  {category:<20}")
        if target:
            parts.append(f"  {target:<30}")
        if status_code is not None:
            parts.append(f"  {status_code}")
        if time_str:
            parts.append(f"  {time_str:>8}")

        line = "".join(parts)
        console.print(line)

        # Print detail on failure
        if detail and not passed:
            console.print(f"         [dim]{detail}[/dim]")


def _print_summary(outcome) -> None:
    """Print the final summary block."""
    console.print()
    console.print("[bold]TestPilot Summary[/bold]")
    console.print()

    report = outcome.report
    summary = report.get("summary", {})

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Endpoints", str(outcome.endpoints_count))
    table.add_row("Cases", str(outcome.cases_count))
    table.add_row("Passed", f"[green]{outcome.passed_count}[/green]")
    table.add_row("Failed", f"[red]{outcome.failed_count}[/red]" if outcome.failed_count else "0")
    table.add_row("Errors", f"[yellow]{outcome.errors_count}[/yellow]" if outcome.errors_count else "0")

    pass_rate = summary.get("pass_rate", 0.0)
    table.add_row("Pass rate", f"{pass_rate * 100:.1f}%")

    console.print(table)
    console.print()

    if outcome.report_path:
        console.print(f"Report: {outcome.report_path}")


# ── Entry point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    app()
