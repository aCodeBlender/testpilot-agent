"""Natural Language Intent Planner — T0302.

Converts a user's natural-language test goal into a structured ``TestIntent``
using an LLM.  All LLM output is validated deterministically.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from testpilot.domain.intent import TestIntent
from testpilot.domain.spec import ApiEndpoint
from testpilot.llm.client import OpenAICompatibleLLMClient
from testpilot.llm.exceptions import LLMResponseError
from testpilot.planner.intent_exceptions import IntentPlannerError

# ── Endpoint catalog ─────────────────────────────────────────────────────────


def build_endpoint_catalog(endpoints: list[ApiEndpoint]) -> list[dict[str, Any]]:
    """Build a lightweight endpoint catalog for the LLM.

    Only includes fields needed for endpoint selection — no schemas,
    no parameters, no auth info.
    """
    return [
        {
            "id": ep.id,
            "method": ep.method,
            "path": ep.path,
            "summary": ep.summary or "",
            "description": ep.description or "",
            "tags": ep.tags,
        }
        for ep in endpoints
    ]


# ── Prompt construction ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a test endpoint selector. Given a list of available API endpoints and a \
user's test goal, select which endpoints to test.

Rules:
1. ONLY select from the provided endpoint IDs.
2. NEVER invent endpoints not in the list.
3. Output ONLY valid JSON matching this exact schema — no markdown, no explanation:
{
  "selection_mode": "all" | "subset" | "none",
  "selected_endpoint_ids": ["exact-id-from-list"],
  "excluded_methods": ["GET"],
  "focus_areas": ["area1"]
}
4. If the user says "no DELETE" or "skip DELETE", put "DELETE" in excluded_methods.
5. Use exact endpoint IDs from the provided list.
6. selection_mode="all" means test ALL listed endpoints (respecting excluded_methods).
7. selection_mode="subset" means test ONLY the listed selected_endpoint_ids.
8. selection_mode="none" means the goal cannot be mapped to any endpoint."""


def _build_user_prompt(goal: str, catalog: list[dict[str, Any]]) -> str:
    """Build the user prompt with endpoint catalog and goal."""
    lines = ["Available endpoints:\n"]
    for ep in catalog:
        lines.append(f"ID: {ep['id']}")
        lines.append(f"Method: {ep['method']}")
        lines.append(f"Path: {ep['path']}")
        if ep["summary"]:
            lines.append(f"Summary: {ep['summary']}")
        if ep["tags"]:
            lines.append(f"Tags: {', '.join(ep['tags'])}")
        lines.append("")

    lines.append(f"User goal: {goal}")
    return "\n".join(lines)


# ── Hallucination guard ──────────────────────────────────────────────────────


def _validate_intent(
    intent: TestIntent,
    catalog: list[dict[str, Any]],
) -> TestIntent:
    """Validate that all selected endpoint IDs exist in the catalog.

    Raises IntentPlannerError on hallucinated or invalid IDs.
    """
    catalog_ids = {ep["id"] for ep in catalog}

    if intent.selection_mode == "subset":
        if not intent.selected_endpoint_ids:
            raise IntentPlannerError(
                "LLM returned selection_mode='subset' but selected_endpoint_ids is empty."
            )
        for eid in intent.selected_endpoint_ids:
            if eid not in catalog_ids:
                raise IntentPlannerError(
                    f"LLM selected unknown endpoint ID: {eid!r}. "
                    f"Valid IDs: {sorted(catalog_ids)}"
                )

    if intent.selection_mode == "none":
        # "none" is valid — user's goal doesn't map to any endpoint
        pass

    return intent


# ── Public API ───────────────────────────────────────────────────────────────


def plan_intent(
    goal: str,
    endpoint_catalog: list[dict[str, Any]],
    llm_client: OpenAICompatibleLLMClient,
) -> TestIntent:
    """Convert a natural-language goal into a structured TestIntent.

    Parameters
    ----------
    goal:
        The user's natural-language test goal.
    endpoint_catalog:
        Lightweight endpoint catalog (from ``build_endpoint_catalog``).
    llm_client:
        Initialized LLM client.

    Returns
    -------
    TestIntent
        Validated, deduplicated test intent.

    Raises
    ------
    IntentPlannerError
        If the LLM returns invalid JSON, invalid schema, or hallucinated IDs.
    """
    if not endpoint_catalog:
        raise IntentPlannerError("Cannot plan intent: no endpoints in catalog.")

    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(goal, endpoint_catalog)

    # Call LLM
    try:
        raw_response = llm_client.call(system_prompt, user_prompt)
    except Exception as exc:
        raise IntentPlannerError(f"LLM call failed: {exc}") from exc

    # Strip markdown fences if present
    raw_response = raw_response.strip()
    if raw_response.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = raw_response.find("\n")
        if first_newline != -1:
            raw_response = raw_response[first_newline + 1 :]
        # Remove closing fence
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

    # Parse JSON
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise IntentPlannerError(
            f"LLM returned invalid JSON: {exc}. "
            f"Response (first 200 chars): {raw_response[:200]!r}"
        ) from exc

    # Validate schema via Pydantic
    try:
        intent = TestIntent.model_validate(data)
    except ValidationError as exc:
        raise IntentPlannerError(
            f"LLM output does not match TestIntent schema: {exc}"
        ) from exc

    # Hallucination guard
    intent = _validate_intent(intent, endpoint_catalog)

    return intent
