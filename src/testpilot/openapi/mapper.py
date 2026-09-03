"""Domain Mapper — maps a resolved OpenAPI dict to TestPilot domain models.

Input:  resolved dict (output of ``loader.load_openapi``)
Output: ``ApiSpec`` populated with ``ApiEndpoint`` objects

Responsibilities:
- info.title / info.version → ApiSpec
- servers → ApiSpec.servers
- paths + operations → ApiEndpoint list
- path-level + operation-level parameter merge
- operationId generation / dedup
- requestBody (application/json preferred)
- responses keyed by status code
- schema mapping (resolved, no $ref handling needed)
"""

from __future__ import annotations

from typing import Any

from testpilot.domain.spec import ApiSpec, ApiEndpoint
from testpilot.domain.schema import (
    ApiSchema,
    ApiParameter,
    ApiRequestBody,
    ApiResponse,
)
from testpilot.openapi.exceptions import MapperError

# OpenAPI HTTP methods (lowercase, as Prance outputs them).
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def map_to_api_spec(resolved: dict) -> ApiSpec:
    """Map a resolved OpenAPI dict to an ``ApiSpec``.

    Parameters
    ----------
    resolved:
        Fully resolved OpenAPI 3.x dict (all ``$ref`` expanded).

    Returns
    -------
    ApiSpec

    Raises
    ------
    MapperError
        If the dict is malformed or required fields are missing.
    """
    if not isinstance(resolved, dict):
        raise MapperError(f"Expected dict, got {type(resolved).__name__}")

    # ── info ────────────────────────────────────────────────────────────
    info = resolved.get("info") or {}
    title = info.get("title")
    version = info.get("version")
    if not title:
        raise MapperError("OpenAPI spec missing required field: info.title")
    if not version:
        raise MapperError("OpenAPI spec missing required field: info.version")

    # ── servers ─────────────────────────────────────────────────────────
    raw_servers = resolved.get("servers") or []
    servers: list[str] = []
    for s in raw_servers:
        url = s.get("url") if isinstance(s, dict) else s
        if url:
            servers.append(str(url))

    # ── paths → endpoints ───────────────────────────────────────────────
    raw_paths = resolved.get("paths") or {}
    endpoints: list[ApiEndpoint] = []
    seen_ids: set[str] = set()

    for path, path_item in sorted(raw_paths.items()):
        if not isinstance(path_item, dict):
            continue

        # Path-level parameters (shared across all operations in this path).
        path_params_raw: list[dict] = path_item.get("parameters") or []

        for method_lower, operation in sorted(path_item.items()):
            if method_lower not in _HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            endpoint = _build_endpoint(
                path=path,
                method_lower=method_lower,
                operation=operation,
                path_level_params=path_params_raw,
                seen_ids=seen_ids,
            )
            endpoints.append(endpoint)

    return ApiSpec(
        title=title,
        version=version,
        servers=servers,
        endpoints=endpoints,
    )


# ── Internal helpers ────────────────────────────────────────────────────────


def _build_endpoint(
    *,
    path: str,
    method_lower: str,
    operation: dict,
    path_level_params: list[dict],
    seen_ids: set[str],
) -> ApiEndpoint:
    """Build a single ``ApiEndpoint`` from an OpenAPI operation dict."""
    method = method_lower.upper()

    # ── id ──────────────────────────────────────────────────────────────
    raw_op_id = operation.get("operationId")
    endpoint_id = _make_endpoint_id(raw_op_id, method, path, seen_ids)
    seen_ids.add(endpoint_id)

    # ── parameters (merge path-level + operation-level) ─────────────────
    merged_params = _merge_parameters(path_level_params, operation.get("parameters") or [])
    parameters = [_map_parameter(p) for p in merged_params]

    # ── requestBody ─────────────────────────────────────────────────────
    request_body = _map_request_body(operation.get("requestBody"))

    # ── responses ───────────────────────────────────────────────────────
    responses = _map_responses(operation.get("responses") or {})

    return ApiEndpoint(
        id=endpoint_id,
        path=path,
        method=method,
        operation_id=raw_op_id,
        summary=operation.get("summary"),
        description=operation.get("description"),
        tags=operation.get("tags") or [],
        deprecated=operation.get("deprecated", False),
        parameters=parameters,
        request_body=request_body,
        responses=responses,
    )


def _make_endpoint_id(
    raw_op_id: str | None,
    method: str,
    path: str,
    seen_ids: set[str],
) -> str:
    """Generate a stable, unique endpoint ID.

    Priority: operationId → synthetic ``{method}_{path_slugged}``.
    Deduplicates by appending ``_2``, ``_3``, … when collisions occur.
    """
    if raw_op_id:
        base = raw_op_id
    else:
        # /users/{id}/posts → users_id_posts
        slug = path.strip("/").replace("{", "").replace("}", "").replace("/", "_")
        base = f"{method.lower()}_{slug}"

    candidate = base
    counter = 2
    while candidate in seen_ids:
        candidate = f"{base}_{counter}"
        counter += 1

    return candidate


def _merge_parameters(
    path_level: list[dict],
    operation_level: list[dict],
) -> list[dict]:
    """Merge path-level and operation-level parameters.

    Operation-level parameters override path-level parameters with the
    same ``(name, in)`` key.  The result preserves operation-level order
    first, then any remaining path-level parameters.
    """
    key = lambda p: (p.get("name", ""), p.get("in", ""))

    # Index path-level by key.
    by_key: dict[tuple[str, str], dict] = {}
    for p in path_level:
        by_key[key(p)] = p

    # Operation-level overrides.
    result_keys: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for p in operation_level:
        k = key(p)
        by_key[k] = p  # override
        result_keys.add(k)
        merged.append(p)

    # Append remaining path-level params that were not overridden.
    for p in path_level:
        k = key(p)
        if k not in result_keys:
            merged.append(by_key[k])

    return merged


def _map_parameter(raw: dict) -> ApiParameter:
    """Map a single resolved OpenAPI parameter dict to ``ApiParameter``."""
    return ApiParameter(
        name=raw.get("name", ""),
        location=raw.get("in", "query"),
        required=raw.get("required", False),
        deprecated=raw.get("deprecated", False),
        description=raw.get("description"),
        param_schema=_map_schema(raw.get("schema") or {}),
    )


def _map_request_body(raw: dict | None) -> ApiRequestBody | None:
    """Map an OpenAPI requestBody dict to ``ApiRequestBody``.

    Prefers ``application/json``; falls back to the first content type found.
    """
    if not raw or not isinstance(raw, dict):
        return None

    content = raw.get("content") or {}
    if not content:
        return ApiRequestBody(
            required=raw.get("required", False),
            description=raw.get("description"),
        )

    # Prefer application/json; fallback to first available content type.
    if "application/json" in content:
        media_type = "application/json"
        media_obj = content["application/json"]
    else:
        media_type = next(iter(content))
        media_obj = content[media_type]

    schema_raw = (media_obj or {}).get("schema") or {}
    return ApiRequestBody(
        required=raw.get("required", False),
        content_type=media_type,
        description=raw.get("description"),
        body_schema=_map_schema(schema_raw),
    )


def _map_responses(raw: dict[str, Any]) -> dict[str, ApiResponse]:
    """Map OpenAPI responses dict to ``dict[str, ApiResponse]``.

    Status codes are the dict keys; ``ApiResponse`` does NOT store them.
    """
    responses: dict[str, ApiResponse] = {}
    for status_code, resp_obj in sorted(raw.items()):
        if not isinstance(resp_obj, dict):
            continue

        # Try to extract content schema (prefer application/json).
        content_schema: ApiSchema | None = None
        content = resp_obj.get("content") or {}
        if content:
            if "application/json" in content:
                media_obj = content["application/json"]
            else:
                media_obj = next(iter(content.values()), None)
            if isinstance(media_obj, dict):
                schema_raw = media_obj.get("schema")
                if schema_raw:
                    content_schema = _map_schema(schema_raw)

        responses[str(status_code)] = ApiResponse(
            description=resp_obj.get("description"),
            content_schema=content_schema,
        )

    return responses


def _map_schema(raw: dict) -> ApiSchema:
    """Recursively map a resolved JSON Schema dict to ``ApiSchema``.

    Since the Loader (Prance) has already resolved all ``$ref``, we only
    need to map the fields that ``ApiSchema`` supports.
    """
    if not isinstance(raw, dict):
        return ApiSchema()

    # Recursive properties.
    raw_props = raw.get("properties")
    properties: dict[str, ApiSchema] | None = None
    if isinstance(raw_props, dict):
        properties = {name: _map_schema(prop) for name, prop in raw_props.items()}

    # Recursive items.
    raw_items = raw.get("items")
    items: ApiSchema | None = None
    if isinstance(raw_items, dict):
        items = _map_schema(raw_items)

    # additional_properties can be bool or schema.
    raw_ap = raw.get("additionalProperties")
    additional_properties: bool | ApiSchema | None = None
    if isinstance(raw_ap, dict):
        additional_properties = _map_schema(raw_ap)
    elif isinstance(raw_ap, bool):
        additional_properties = raw_ap

    return ApiSchema(
        type=raw.get("type"),
        format=raw.get("format"),
        properties=properties,
        items=items,
        required=raw.get("required") or [],
        enum=raw.get("enum") or [],
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        exclusive_minimum=bool(raw.get("exclusiveMinimum", False)),
        exclusive_maximum=bool(raw.get("exclusiveMaximum", False)),
        multiple_of=raw.get("multipleOf"),
        min_length=raw.get("minLength"),
        max_length=raw.get("maxLength"),
        pattern=raw.get("pattern"),
        min_items=raw.get("minItems"),
        max_items=raw.get("maxItems"),
        unique_items=raw.get("uniqueItems"),
        additional_properties=additional_properties,
        nullable=raw.get("nullable", False),
        description=raw.get("description"),
        example=raw.get("example"),
        default=raw.get("default"),
        read_only=raw.get("readOnly", False),
        write_only=raw.get("writeOnly", False),
    )
