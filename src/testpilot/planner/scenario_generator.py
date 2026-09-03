"""Deterministic Scenario Generator — T0201.

Input:  ApiEndpoint
Output: list[TestScenario]

Generates test scenarios describing *what* to test, without constructing
actual HTTP requests.  Covers: happy_path, required_missing, null, wrong_type.
"""

from __future__ import annotations

import itertools

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody
from testpilot.domain.testing import TestScenario


def generate_scenarios(
    endpoint: ApiEndpoint,
    max_cases: int = 20,
) -> list[TestScenario]:
    """Generate deterministic test scenarios for *endpoint*.

    Parameters
    ----------
    endpoint:
        The API endpoint to generate scenarios for.
    max_cases:
        Maximum number of scenarios to return.  ``happy_path`` is always
        included; remaining slots are filled by negative scenarios via
        round-robin across categories: required_missing → null → wrong_type.

    Returns
    -------
    list[TestScenario]
        A list of scenarios (always includes at least one ``happy_path``).
    """
    if max_cases < 1:
        raise ValueError("max_cases must be >= 1")

    seen_ids: set[str] = set()
    buckets: dict[str, list[TestScenario]] = {
        "required_missing": [],
        "null": [],
        "wrong_type": [],
    }

    def _add(category: str, name: str, target_location=None, target_path=None, rationale=None):
        sid = _make_id(endpoint.id, category, target_path, seen_ids)
        seen_ids.add(sid)
        scenario = TestScenario(
            id=sid,
            endpoint_id=endpoint.id,
            source="deterministic",
            category=category,
            name=name,
            target_location=target_location,
            target_path=target_path,
            rationale=rationale,
        )
        if category in buckets:
            buckets[category].append(scenario)
        return scenario

    # 1. happy_path — always one per endpoint
    happy = _add("happy_path", f"Happy path for {endpoint.method} {endpoint.path}")

    # 2. required_missing
    _collect_required_missing(endpoint, _add)

    # 3. null (non-nullable fields) — skip path params (no reliable HTTP null)
    _collect_null(endpoint, _add)

    # 4. wrong_type — including path params
    _collect_wrong_type(endpoint, _add)

    # Interleave negative scenarios via round-robin
    negatives = list(itertools.zip_longest(
        buckets["required_missing"],
        buckets["null"],
        buckets["wrong_type"],
    ))
    flat_negatives: list[TestScenario] = []
    for group in negatives:
        for s in group:
            if s is not None:
                flat_negatives.append(s)

    # Build final list: happy_path + interleaved negatives, capped at max_cases
    scenarios = [happy] + flat_negatives[: max_cases - 1]
    return scenarios


# ── ID generation ────────────────────────────────────────────────────────────


def _make_id(
    endpoint_id: str,
    category: str,
    target_path: str | None,
    seen: set[str],
) -> str:
    suffix = target_path.replace(".", "_") if target_path else "none"
    base = f"sc-{endpoint_id}-{category}-{suffix}"
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


# ── required_missing ─────────────────────────────────────────────────────────


def _collect_required_missing(
    endpoint: ApiEndpoint,
    _add,
) -> None:
    # Required parameters (query, header, cookie) — skip path params
    for param in endpoint.parameters:
        if param.required and param.location != "path":
            _add(
                "required_missing",
                f"Missing required {param.location} param '{param.name}'",
                target_location=param.location,
                target_path=param.name,
                rationale=f"{param.name} is required in {param.location}",
            )

    # Required body properties — walk schema.required regardless of requestBody.required.
    # requestBody.required means "body must exist"; schema.required means
    # "these properties must exist when body is present".
    # We always send a body, so schema.required always applies.
    if endpoint.request_body:
        _walk_body_required(endpoint.request_body.body_schema, "body", _add)


def _walk_body_required(
    schema: ApiSchema,
    prefix: str,
    _add,
) -> None:
    """Walk object properties and generate required_missing for each required field."""
    if schema.type != "object" or not schema.properties:
        return
    for prop_name in schema.required:
        prop_schema = schema.properties.get(prop_name)
        if prop_schema is None:
            continue
        # Skip readOnly properties — they are server-generated, not sent in requests
        if prop_schema.read_only:
            continue
        dotted = f"{prefix}.{prop_name}" if prefix else prop_name
        _add(
            "required_missing",
            f"Missing required body field '{dotted}'",
            target_location="body",
            target_path=dotted,
            rationale=f"{dotted} is required in request body",
        )
        # Recurse into nested objects
        if prop_schema.type == "object":
            _walk_body_required(prop_schema, dotted, _add)


# ── null ─────────────────────────────────────────────────────────────────────


def _collect_null(
    endpoint: ApiEndpoint,
    _add,
) -> None:
    # Non-nullable parameters — skip path params (no reliable HTTP null expression)
    for param in endpoint.parameters:
        if param.location == "path":
            continue
        if not param.param_schema.nullable:
            _add(
                "null",
                f"Null value for {param.location} param '{param.name}'",
                target_location=param.location,
                target_path=param.name,
                rationale=f"{param.name} does not allow null",
            )

    # Non-nullable body properties (recursive)
    if endpoint.request_body:
        _walk_body_nullable(endpoint.request_body.body_schema, "body", _add)


def _walk_body_nullable(
    schema: ApiSchema,
    prefix: str,
    _add,
) -> None:
    """Walk object properties and generate null scenarios for non-nullable fields."""
    if schema.type != "object" or not schema.properties:
        return
    for prop_name, prop_schema in schema.properties.items():
        # Skip readOnly properties — they are server-generated, not sent in requests
        if prop_schema.read_only:
            continue
        if not prop_schema.nullable:
            dotted = f"{prefix}.{prop_name}" if prefix else prop_name
            _add(
                "null",
                f"Null value for body field '{dotted}'",
                target_location="body",
                target_path=dotted,
                rationale=f"{dotted} does not allow null",
            )
            if prop_schema.type == "object":
                _walk_body_nullable(prop_schema, dotted, _add)


# ── wrong_type ───────────────────────────────────────────────────────────────


def _collect_wrong_type(
    endpoint: ApiEndpoint,
    _add,
) -> None:
    # Parameters with explicit type — including path params
    for param in endpoint.parameters:
        if param.param_schema.type:
            _add(
                "wrong_type",
                f"Wrong type for {param.location} param '{param.name}'",
                target_location=param.location,
                target_path=param.name,
                rationale=f"{param.name} expects type {param.param_schema.type}",
            )

    # Body properties with explicit type (recursive)
    if endpoint.request_body:
        _walk_body_wrong_type(endpoint.request_body.body_schema, "body", _add)


def _walk_body_wrong_type(
    schema: ApiSchema,
    prefix: str,
    _add,
) -> None:
    """Walk object properties and generate wrong_type for typed fields."""
    if schema.type != "object" or not schema.properties:
        return
    for prop_name, prop_schema in schema.properties.items():
        # Skip readOnly properties — they are server-generated, not sent in requests
        if prop_schema.read_only:
            continue
        if prop_schema.type:
            dotted = f"{prefix}.{prop_name}" if prefix else prop_name
            _add(
                "wrong_type",
                f"Wrong type for body field '{dotted}'",
                target_location="body",
                target_path=dotted,
                rationale=f"{dotted} expects type {prop_schema.type}",
            )
            if prop_schema.type == "object":
                _walk_body_wrong_type(prop_schema, dotted, _add)
