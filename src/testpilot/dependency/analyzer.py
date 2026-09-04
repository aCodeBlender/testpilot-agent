"""Conservative deterministic dependency inference.

This module infers dependencies between API endpoints by examining
path structure, parameter names, and OpenAPI schema types — NO LLM involved.

Rules (all must match for a dependency to be inferred):

1. **Path-parameter rule**: A path segment ``{param}`` in the *consumer*
   endpoint must have a matching camelCase/snake_case counterpart in a
   *producer* endpoint's non-parameter path segment.

2. **Resource-family rule**: The first non-parameter path segment of the
   producer and consumer must map to the same resource family
   (e.g. "/users" and "/users/{id}" both map to "user").

3. **Pointer rule**: The default response pointer is ``/{id}`` where
   ``id`` is the path-parameter name stripped of the resource prefix
   (e.g. ``userId`` -> ``id``).

4. **Schema-type rule**: The JSON Schema type of the producer's response
   field and the consumer's parameter must be compatible.  If either type
   is unknown (``None``), the dependency is NOT established.

Design choice: this module is intentionally conservative.  It will
produce **fewer** dependencies rather than risk false positives.
"""

from __future__ import annotations

import re
from typing import Sequence

from testpilot.domain.schema import ApiSchema
from testpilot.domain.spec import ApiEndpoint
from testpilot.dependency.models import ApiDependency, DependencySource, DependencyTarget
from testpilot.dependency.resource_family import resource_family_from_path

# Matches {paramName} in path templates
_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")

# Scalar types we consider for compatibility checking.
_SCALAR_TYPES = frozenset({"string", "integer", "number", "boolean"})


# ---------------------------------------------------------------------------
# Schema type resolution
# ---------------------------------------------------------------------------


def _resolve_pointer_schema(schema: ApiSchema, pointer: str) -> str | None:
    """Resolve a JSON Pointer against an ``ApiSchema`` and return the type.

    Returns the JSON Schema type string (e.g. "string", "integer") or
    ``None`` when the type cannot be determined (missing, implicit, or
    the pointer traverses through a non-object).
    """
    if not pointer.startswith("/"):
        return None

    parts = pointer.lstrip("/").split("/")
    current = schema

    for part in parts:
        # RFC 6901 unescaping
        part = part.replace("~1", "/").replace("~0", "~")

        # Must be an object with properties to traverse further
        if current.type and current.type != "object":
            return None
        if current.properties is None:
            return None
        if part not in current.properties:
            return None
        current = current.properties[part]

    # We've reached the target — return its type
    return current.type


def _get_consumer_param_type(
    consumer: ApiEndpoint,
    param_name: str,
) -> str | None:
    """Look up the JSON Schema type of a path parameter on the consumer.

    Returns the type string or ``None`` when the parameter or its type
    is not declared.
    """
    for param in consumer.parameters:
        if param.name == param_name and param.location == "path":
            return param.param_schema.type
    return None


def _get_producer_response_type(
    producer: ApiEndpoint,
    pointer: str,
    status_codes: list[int],
) -> str | None:
    """Resolve the JSON Schema type at *pointer* in the producer's response.

    Checks the first matching status code in *status_codes* whose
    ``content_schema`` can be resolved.  Returns ``None`` when the
    type cannot be determined.
    """
    for code_str, response in producer.responses.items():
        # Match status code (exact or wildcard like "2XX")
        try:
            code_int = int(code_str)
        except ValueError:
            # e.g. "2XX", "default"
            if code_str.upper().startswith("2"):
                code_int = 200
            else:
                continue
        if code_int not in status_codes:
            continue
        if response.content_schema is None:
            continue
        resolved = _resolve_pointer_schema(response.content_schema, pointer)
        if resolved is not None:
            return resolved
    return None


def _types_compatible(producer_type: str | None, consumer_type: str | None) -> bool:
    """Check whether producer and consumer schema types are compatible.

    Conservative rules:
    - Both must be known (not None).
    - Both must be scalar types (string, integer, number, boolean).
    - Exact match required — no coercion (integer ≠ number, etc.).
    """
    if producer_type is None or consumer_type is None:
        return False
    if producer_type not in _SCALAR_TYPES:
        return False
    if consumer_type not in _SCALAR_TYPES:
        return False
    return producer_type == consumer_type

# Strips resource prefix from camelCase parameter names:
#   userId -> id, orderId -> order_id (kept as-is for matching)
_PREFIX_STRIP_RE = re.compile(
    r"^(?P<prefix>[a-z]+)(?P<suffix>[A-Z][a-zA-Z0-9]*)$"
)


def _strip_resource_prefix(param_name: str) -> str | None:
    """Strip a resource prefix from a camelCase parameter name.

    Examples:
        userId   -> id
        orderId  -> Id  (lowercased to "id" by caller)
        postId   -> id
        id       -> None  (no prefix to strip)
    """
    m = _PREFIX_STRIP_RE.match(param_name)
    if m:
        return m.group("suffix").lower()
    return None


def _path_segments(path: str) -> list[str]:
    """Return non-empty, non-parameter path segments."""
    return [
        seg for seg in path.strip("/").split("/")
        if seg and not (seg.startswith("{") and seg.endswith("}"))
    ]


def _path_params(path: str) -> list[str]:
    """Return parameter names from path template."""
    return _PATH_PARAM_RE.findall(path)


def _candidate_source_pointer(param_name: str) -> str:
    """Derive the most likely response-pointer for a path parameter.

    For ``userId`` -> ``/id``, for ``id`` -> ``/id``, for ``orderId`` -> ``/id``.
    """
    stripped = _strip_resource_prefix(param_name)
    key = stripped if stripped else param_name
    return f"/{key.lower()}"


def _param_implies_family(param_name: str) -> str | None:
    """Extract the resource family implied by a camelCase parameter name.

    Examples:
        userId   -> "user"
        orderId  -> "order"
        id       -> None  (no prefix to extract)
    """
    m = _PREFIX_STRIP_RE.match(param_name)
    if m:
        return m.group("prefix").lower()
    return None


def _is_list_endpoint(ep: ApiEndpoint) -> bool:
    """True when *ep* is a list-type endpoint.

    A list endpoint is a GET (or HEAD) with no path parameters — it
    returns ``[...]`` (a JSON array), not a single resource.
    POST/PUT/PATCH without path params are create/update endpoints that
    return a single resource — they are NOT list endpoints.
    """
    if _path_params(ep.path):
        return False
    return ep.method in ("GET", "HEAD")


def _is_scalar_producer(ep: ApiEndpoint) -> bool:
    """True when *ep* can produce a scalar value.

    Qualifying endpoints:
    - Endpoints with path params (singleton-by-id, e.g. GET /users/{id}).
    - POST/PUT/PATCH endpoints (create/update — return a single resource).

    Non-qualifying:
    - GET/HEAD without path params (list endpoints — return arrays).
    """
    if _is_list_endpoint(ep):
        return False
    return True


def infer_dependencies(
    endpoints: Sequence[ApiEndpoint],
    default_status_codes: list[int] | None = None,
) -> list[ApiDependency]:
    """Infer dependencies deterministically from endpoint structure.

    Parameters
    ----------
    endpoints:
        All endpoints from the OpenAPI spec.
    default_status_codes:
        Status codes to register on each DependencySource.  Defaults to
        ``[200, 201]``.

    Returns
    -------
    list[ApiDependency]
        Inferred dependency edges (may be empty).

    Notes
    -----
    Ambiguous cases (multiple equally-qualified producers for the same
    consumer+parameter) are **not** bound — the dependency is left
    unresolved.  This is intentional: the conservative approach prefers
    zero false positives over coverage.
    """
    if default_status_codes is None:
        default_status_codes = [200, 201]

    deps: list[ApiDependency] = []

    # Index endpoints by resource family
    family_index: dict[str, list[ApiEndpoint]] = {}
    for ep in endpoints:
        family = resource_family_from_path(ep.path)
        if family:
            family_index.setdefault(family, []).append(ep)

    # For each endpoint with path parameters, try to find a producer
    for consumer in endpoints:
        params = _path_params(consumer.path)
        if not params:
            continue

        consumer_family = resource_family_from_path(consumer.path)

        for param_name in params:
            pointer = _candidate_source_pointer(param_name)

            # Find producers in the same resource family that can
            # produce a scalar value.
            #
            # Additionally, the parameter name must make sense for the
            # producer's family.  For "userId", the implied family is
            # "user" — only producers in the "user" family qualify.
            # For a bare "id" (no prefix), we fall back to the
            # consumer's family.
            implied_family = _param_implies_family(param_name)
            target_family = implied_family if implied_family else consumer_family

            candidates = []
            if target_family and target_family in family_index:
                for producer in family_index[target_family]:
                    if producer.id == consumer.id:
                        continue
                    if not _is_scalar_producer(producer):
                        continue
                    producer_params = _path_params(producer.path)
                    if param_name not in producer_params:
                        candidates.append(producer)

            if not candidates:
                continue

            # Ambiguous: multiple equally-qualified producers → skip.
            # We cannot deterministically choose, so we leave the
            # dependency unresolved rather than guess.
            if len(candidates) > 1:
                continue

            producer = candidates[0]

            # ── Schema type compatibility ────────────────────────────
            # Both producer response field type and consumer parameter
            # type must be known and match exactly.  Unknown type → skip.
            producer_type = _get_producer_response_type(
                producer, pointer, default_status_codes
            )
            consumer_type = _get_consumer_param_type(consumer, param_name)

            if not _types_compatible(producer_type, consumer_type):
                continue

            dep = ApiDependency(
                source=DependencySource(
                    endpoint_id=producer.id,
                    response_pointer=pointer,
                    status_codes=default_status_codes,
                    schema_type=producer_type,
                ),
                target=DependencyTarget(
                    endpoint_id=consumer.id,
                    parameter_name=param_name,
                    parameter_location="path",
                    schema_type=consumer_type,
                ),
                confidence="deterministic",
                resource_family=consumer_family,
                notes=(
                    f"Path parameter '{param_name}' in {consumer.method} {consumer.path} "
                    f"likely produced by {producer.method} {producer.path}"
                ),
            )
            deps.append(dep)

    return deps
