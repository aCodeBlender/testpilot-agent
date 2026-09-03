"""Semantic Scenario Planner — Phase 3B.

Input:  ApiEndpoint + optional focus areas
Output: list[SemanticScenarioProposal]

Uses an LLM to propose test scenarios that go beyond deterministic
schema rules (happy_path, required_missing, null, wrong_type).

All LLM output is validated deterministically before being returned.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from testpilot.domain.schema import ApiSchema, ApiParameter
from testpilot.domain.semantic import SemanticScenarioProposal
from testpilot.domain.spec import ApiEndpoint
from testpilot.llm.client import OpenAICompatibleLLMClient
from testpilot.planner.semantic_exceptions import SemanticPlannerError
from testpilot.planner.semantic_validation import (
    deduplicate_proposals,
    validate_proposals,
)

# ── Endpoint prompt context ─────────────────────────────────────────────────


def build_endpoint_prompt_context(endpoint: ApiEndpoint) -> dict[str, Any]:
    """Build minimal endpoint context for the LLM prompt.

    Only includes information relevant to semantic test planning.
    Excludes: API keys, bearer tokens, auth values, response data,
    unrelated endpoints.
    """
    context: dict[str, Any] = {
        "endpoint_id": endpoint.id,
        "method": endpoint.method,
        "path": endpoint.path,
    }

    if endpoint.summary:
        context["summary"] = endpoint.summary
    if endpoint.description:
        context["description"] = endpoint.description
    if endpoint.tags:
        context["tags"] = endpoint.tags

    # Parameters
    if endpoint.parameters:
        context["parameters"] = [
            _build_param_context(p) for p in endpoint.parameters
        ]

    # Request body schema
    if endpoint.request_body:
        context["request_body"] = {
            "required": endpoint.request_body.required,
            "content_type": endpoint.request_body.content_type,
            "schema": _build_schema_context(endpoint.request_body.body_schema),
        }

    return context


def _build_param_context(param: ApiParameter) -> dict[str, Any]:
    """Build parameter context for the prompt."""
    ctx: dict[str, Any] = {
        "location": param.location,
        "name": param.name,
        "required": param.required,
    }
    schema_ctx = _build_schema_context(param.param_schema)
    if schema_ctx:
        ctx["schema"] = schema_ctx
    return ctx


def _build_schema_context(schema: ApiSchema) -> dict[str, Any]:
    """Build schema context for the prompt.

    Includes only fields relevant for semantic test planning:
    type, format, enum, constraints, nullable, readOnly/writeOnly.
    """
    ctx: dict[str, Any] = {}

    if schema.type:
        ctx["type"] = schema.type
    if schema.format:
        ctx["format"] = schema.format
    if schema.enum:
        ctx["enum"] = schema.enum
    if schema.minimum is not None:
        ctx["minimum"] = schema.minimum
    if schema.maximum is not None:
        ctx["maximum"] = schema.maximum
    if schema.min_length is not None:
        ctx["minLength"] = schema.min_length
    if schema.max_length is not None:
        ctx["maxLength"] = schema.max_length
    if schema.nullable:
        ctx["nullable"] = True
    if schema.read_only:
        ctx["readOnly"] = True
    if schema.write_only:
        ctx["writeOnly"] = True

    # Nested object properties
    if schema.properties:
        ctx["properties"] = {
            name: _build_schema_context(prop)
            for name, prop in schema.properties.items()
        }
        if schema.required:
            ctx["required"] = schema.required

    # Array items
    if schema.items:
        ctx["items"] = _build_schema_context(schema.items)

    return ctx


# ── Prompt construction ─────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a semantic test scenario planner. Given an API endpoint's schema, \
propose test scenarios that go BEYOND basic mechanical validation.

The deterministic planner ALREADY covers:
- happy_path (valid request)
- required_missing (missing required fields)
- null (null values for non-nullable fields)
- wrong_type (type mismatches)

Do NOT reproduce those unless semantic meaning materially changes the case.

Focus on scenarios requiring semantic interpretation:
- email format semantics (e.g. "not-an-email")
- duplicate identifiers (e.g. register same email twice)
- business boundaries (e.g. age=0, age=151 for 0..150)
- state transitions (e.g. cancel already-cancelled order)
- authorization intent (e.g. access other user's resource)
- relationships between fields/resources
- domain-specific invalid values

Rules:
1. Output ONLY valid JSON — no markdown, no explanation, no chain-of-thought.
2. Output a JSON array of proposal objects.
3. Each proposal must have exactly these fields:
   - endpoint_id (string, must match the provided endpoint)
   - name (string, short human-readable)
   - description (string, detailed)
   - rationale (string, why this matters)
   - category (one of: format_violation, boundary, business_rule, duplicate_resource, invalid_state, authorization, relationship, semantic)
   - target_location (one of: path, query, header, cookie, body, auth, or null)
   - target_path (string or null — dotted path for nested body fields)
   - strategy (one of: mutate_field, omit_field, reuse_existing_value, custom_value, multi_step_required, analysis_only)
   - proposed_value (any JSON value or null)
   - requires_state (boolean)
4. If a scenario requires prior API state (e.g. create-then-duplicate), \
set strategy="multi_step_required" and requires_state=true.
5. Do NOT invent fields or paths not in the provided schema.
6. Do NOT propose scenarios for readOnly fields.
7. If no semantic scenarios apply, return an empty array [].
"""


def _build_user_prompt(
    endpoint_context: dict[str, Any],
    focus_areas: list[str] | None = None,
) -> str:
    """Build the user prompt with endpoint context."""
    lines = ["Endpoint to analyze:\n"]
    lines.append(json.dumps(endpoint_context, indent=2))

    if focus_areas:
        lines.append(f"\nFocus areas: {', '.join(focus_areas)}")

    lines.append(
        "\nPropose semantic test scenarios as a JSON array. "
        "Return ONLY the JSON array, nothing else."
    )
    return "\n".join(lines)


# ── Public API ──────────────────────────────────────────────────────────────


def plan_semantic_scenarios(
    endpoint: ApiEndpoint,
    llm_client: OpenAICompatibleLLMClient,
    focus_areas: list[str] | None = None,
) -> list[SemanticScenarioProposal]:
    """Plan semantic test scenarios for a single endpoint.

    Parameters
    ----------
    endpoint:
        The API endpoint to analyze.
    llm_client:
        Initialized LLM client.
    focus_areas:
        Optional advisory focus areas (e.g. ["authorization", "parameter validation"]).
        These are hints to the LLM — the planner still stays within the endpoint.

    Returns
    -------
    list[SemanticScenarioProposal]
        Validated, deduplicated semantic proposals.

    Raises
    ------
    SemanticPlannerError
        If the LLM returns invalid JSON, invalid schema, hallucinated fields,
        or proposals that fail validation guards.
    """
    # Build prompt context
    context = build_endpoint_prompt_context(endpoint)
    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(context, focus_areas)

    # Call LLM
    try:
        raw_response = llm_client.call(system_prompt, user_prompt)
    except Exception as exc:
        raise SemanticPlannerError(f"LLM call failed: {exc}") from exc

    # Strip markdown fences if present
    raw_response = raw_response.strip()
    if raw_response.startswith("```"):
        first_newline = raw_response.find("\n")
        if first_newline != -1:
            raw_response = raw_response[first_newline + 1:]
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

    # Parse JSON
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise SemanticPlannerError(
            f"LLM returned invalid JSON: {exc}. "
            f"Response (first 200 chars): {raw_response[:200]!r}"
        ) from exc

    # Must be a list
    if not isinstance(data, list):
        raise SemanticPlannerError(
            f"LLM returned {type(data).__name__}, expected JSON array. "
            f"Response (first 200 chars): {raw_response[:200]!r}"
        )

    # Empty list is valid — no semantic scenarios for this endpoint
    if not data:
        return []

    # Parse each proposal via Pydantic
    proposals: list[SemanticScenarioProposal] = []
    for i, item in enumerate(data):
        try:
            proposal = SemanticScenarioProposal.model_validate(item)
        except ValidationError as exc:
            raise SemanticPlannerError(
                f"LLM proposal #{i} does not match schema: {exc}"
            ) from exc
        proposals.append(proposal)

    # Deterministic validation
    proposals = validate_proposals(proposals, endpoint)

    # Deduplication
    proposals = deduplicate_proposals(proposals)

    return proposals
