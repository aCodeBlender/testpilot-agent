"""Deterministic schema validation — T0205.

Validates a Python value against an ``ApiSchema`` without LLM or
external dependencies.  Returns ``None`` when the value is valid
or a short error string on the first violation found.
"""

from __future__ import annotations

import re
from typing import Any

from testpilot.domain.schema import ApiSchema


def validate_schema(
    value: Any,
    schema: ApiSchema,
    *,
    direction: str = "request",
) -> str | None:
    """Validate *value* against *schema*.

    Parameters
    ----------
    value:
        The value to validate.
    schema:
        The schema to validate against.
    direction:
        ``"request"`` (default) or ``"response"``.  In response mode,
        ``writeOnly`` properties are excluded from ``required`` checks.

    Returns
    -------
    str | None
        ``None`` if valid, or a human-readable error string describing
        the first violation found.  Does **not** raise on validation failure.
    """
    return _validate(value, schema, path="", direction=direction)


# ── internal ────────────────────────────────────────────────────────────────


def _validate(
    value: Any,
    schema: ApiSchema,
    *,
    path: str,
    direction: str = "request",
) -> str | None:
    """Recursive validation.  *path* is the dotted location for error messages."""

    # ── nullable ──
    if value is None:
        if schema.nullable:
            return None
        if schema.type == "null":
            return None
        return _err(path, "expected non-null, got null")

    # ── enum ──
    if schema.enum is not None and len(schema.enum) > 0:
        if value not in schema.enum:
            return _err(path, f"expected one of {schema.enum}, got {value!r}")

    # ── type dispatch ──
    t = schema.type

    if t == "object" or (t is None and isinstance(value, dict)):
        return _validate_object(value, schema, path=path, direction=direction)

    if t == "array" or (t is None and isinstance(value, list)):
        return _validate_array(value, schema, path=path, direction=direction)

    if t == "string" or (t is None and isinstance(value, str)):
        return _validate_string(value, schema, path=path)

    if t == "integer":
        return _validate_integer(value, schema, path=path)

    if t == "number":
        return _validate_number(value, schema, path=path)

    if t == "boolean":
        return _validate_boolean(value, schema, path=path)

    if t == "null":
        if value is None:
            return None
        return _err(path, f"expected null, got {type(value).__name__}")

    # Unknown type — pass (don't block on unmodeled types)
    return None


# ── object ──────────────────────────────────────────────────────────────────


def _validate_object(
    value: Any,
    schema: ApiSchema,
    *,
    path: str,
    direction: str = "request",
) -> str | None:
    if not isinstance(value, dict):
        return _err(path, f"expected object, got {type(value).__name__}")

    # required properties
    for req in (schema.required or []):
        if req not in value:
            # writeOnly required fields are NOT required in responses
            if direction == "response":
                prop_schema = (schema.properties or {}).get(req)
                if prop_schema is not None and prop_schema.write_only:
                    continue
            return _err(_dot(path, req), "required property missing")

    # additional_properties
    allow_additional = schema.additional_properties
    declared = set(schema.properties.keys()) if schema.properties else set()

    if allow_additional is False:
        for key in value:
            if key not in declared:
                return _err(_dot(path, key), "unexpected property (additionalProperties=false)")
    elif isinstance(allow_additional, ApiSchema):
        for key in value:
            if key not in declared:
                err = _validate(value[key], allow_additional, path=_dot(path, key), direction=direction)
                if err is not None:
                    return err

    # recursive property validation
    if schema.properties:
        for prop_name, prop_schema in schema.properties.items():
            if prop_name in value:
                err = _validate(value[prop_name], prop_schema, path=_dot(path, prop_name), direction=direction)
                if err:
                    return err

    return None


# ── array ───────────────────────────────────────────────────────────────────


def _validate_array(
    value: Any,
    schema: ApiSchema,
    *,
    path: str,
    direction: str = "request",
) -> str | None:
    if not isinstance(value, list):
        return _err(path, f"expected array, got {type(value).__name__}")

    if schema.min_items is not None and len(value) < schema.min_items:
        return _err(path, f"minItems={schema.min_items}, got {len(value)}")

    if schema.max_items is not None and len(value) > schema.max_items:
        return _err(path, f"maxItems={schema.max_items}, got {len(value)}")

    if schema.unique_items and len(value) != len(set(_make_hashable(v) for v in value)):
        return _err(path, "uniqueItems violated: duplicate elements")

    if schema.items:
        for i, item in enumerate(value):
            err = _validate(item, schema.items, path=f"{path}[{i}]", direction=direction)
            if err:
                return err

    return None


# ── string ──────────────────────────────────────────────────────────────────


def _validate_string(value: Any, schema: ApiSchema, *, path: str) -> str | None:
    if not isinstance(value, str):
        return _err(path, f"expected string, got {type(value).__name__}")

    if schema.min_length is not None and len(value) < schema.min_length:
        return _err(path, f"minLength={schema.min_length}, got {len(value)}")

    if schema.max_length is not None and len(value) > schema.max_length:
        return _err(path, f"maxLength={schema.max_length}, got {len(value)}")

    if schema.pattern is not None:
        if not re.search(schema.pattern, value):
            return _err(path, f"pattern '{schema.pattern}' not matched")

    return None


# ── integer ─────────────────────────────────────────────────────────────────


def _validate_integer(value: Any, schema: ApiSchema, *, path: str) -> str | None:
    # bool is subclass of int in Python — reject bools for integer type
    if isinstance(value, bool):
        return _err(path, "expected integer, got bool")

    if not isinstance(value, int) or isinstance(value, float):
        return _err(path, f"expected integer, got {type(value).__name__}")

    return _validate_numeric(value, schema, path=path)


# ── number ──────────────────────────────────────────────────────────────────


def _validate_number(value: Any, schema: ApiSchema, *, path: str) -> str | None:
    if isinstance(value, bool):
        return _err(path, "expected number, got bool")

    if not isinstance(value, (int, float)):
        return _err(path, f"expected number, got {type(value).__name__}")

    return _validate_numeric(value, schema, path=path)


# ── boolean ─────────────────────────────────────────────────────────────────


def _validate_boolean(value: Any, schema: ApiSchema, *, path: str) -> str | None:
    if not isinstance(value, bool):
        return _err(path, f"expected boolean, got {type(value).__name__}")
    return None


# ── numeric constraints ────────────────────────────────────────────────────


def _validate_numeric(value: int | float, schema: ApiSchema, *, path: str) -> str | None:
    if schema.minimum is not None:
        if schema.exclusive_minimum:
            if value <= schema.minimum:
                return _err(path, f"expected > {schema.minimum}, got {value}")
        else:
            if value < schema.minimum:
                return _err(path, f"expected >= {schema.minimum}, got {value}")

    if schema.maximum is not None:
        if schema.exclusive_maximum:
            if value >= schema.maximum:
                return _err(path, f"expected < {schema.maximum}, got {value}")
        else:
            if value > schema.maximum:
                return _err(path, f"expected <= {schema.maximum}, got {value}")

    if schema.multiple_of is not None and schema.multiple_of != 0:
        # Use tolerance for floating point
        remainder = abs(value % schema.multiple_of)
        tolerance = abs(schema.multiple_of) * 1e-9
        if remainder > tolerance and abs(remainder - schema.multiple_of) > tolerance:
            return _err(path, f"expected multiple of {schema.multiple_of}, got {value}")

    return None


# ── helpers ─────────────────────────────────────────────────────────────────


def _err(path: str, msg: str) -> str:
    loc = path or "value"
    return f"{loc}: {msg}"


def _dot(parent: str, child: str) -> str:
    return f"{parent}.{child}" if parent else child


def _make_hashable(v: Any) -> Any:
    """Convert a value to a hashable form for uniqueness checks."""
    if isinstance(v, dict):
        return tuple(sorted((k, _make_hashable(val)) for k, val in v.items()))
    if isinstance(v, list):
        return tuple(_make_hashable(item) for item in v)
    return v
