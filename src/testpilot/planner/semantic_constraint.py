"""Request-Schema Constraint Checker — Phase 3B Batch 2 T0321.

Deterministically checks whether a proposed value violates an explicit
OpenAPI request-side constraint.  No LLM calls.

Returns a structured result distinguishing:
  - value is provably invalid (violates=True)
  - value is valid (violates=False)
  - cannot determine (violates=False, no violated constraints)
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from testpilot.domain.schema import ApiSchema

# ── Constraint check status ─────────────────────────────────────────────────

ConstraintStatus = Literal["violates", "valid", "cannot_determine"]
"""Tri-state outcome of a constraint check.

* ``violates`` — the value provably violates an explicit schema constraint.
* ``valid`` — the value satisfies all checked constraints.
* ``cannot_determine`` — the check could not prove validity or violation
  (e.g. unsupported format).  Treat as NOT executable.
"""


# ── Result model ────────────────────────────────────────────────────────────


class ConstraintCheckResult(BaseModel):
    """Result of a deterministic constraint check."""

    __test__ = False

    status: ConstraintStatus = Field(
        description="Tri-state outcome: 'violates', 'valid', or 'cannot_determine'",
    )
    violated_constraints: list[str] = Field(
        default_factory=list,
        description="Names of violated constraints (e.g. 'maximum', 'enum', 'format:email')",
    )
    detail: str = Field(default="", description="Human-readable explanation")

    @property
    def violates(self) -> bool:
        """Convenience: True when status is 'violates'."""
        return self.status == "violates"


# ── Public API ──────────────────────────────────────────────────────────────


def check_constraint(value: Any, schema: ApiSchema) -> ConstraintCheckResult:
    """Check whether *value* violates explicit constraints in *schema*.

    Returns ``violates=True`` only when the violation can be proven
    deterministically from the schema.  Returns ``violates=False`` when
    the value is valid OR when the check cannot determine validity
    (e.g. unsupported format).

    Parameters
    ----------
    value:
        The proposed value to check.
    schema:
        The request-side ApiSchema to check against.

    Returns
    -------
    ConstraintCheckResult
    """
    # None value — check nullable
    if value is None:
        if schema.nullable:
            return ConstraintCheckResult(status="valid")
        return ConstraintCheckResult(
            status="violates",
            violated_constraints=["nullable"],
            detail="null value for non-nullable field",
        )

    # Type check
    type_err = _check_type(value, schema)
    if type_err is not None:
        return type_err

    # Enum check
    if schema.enum:
        if value not in schema.enum:
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["enum"],
                detail=f"expected one of {schema.enum}, got {value!r}",
            )

    # Numeric constraints
    if schema.type in ("integer", "number") and isinstance(value, (int, float)) and not isinstance(value, bool):
        num_err = _check_numeric(value, schema)
        if num_err is not None:
            return num_err

    # String constraints
    if schema.type == "string" and isinstance(value, str):
        str_err = _check_string(value, schema)
        if str_err is not None:
            return str_err

    return ConstraintCheckResult(status="valid")


# ── Type check ──────────────────────────────────────────────────────────────


def _check_type(value: Any, schema: ApiSchema) -> ConstraintCheckResult | None:
    """Check if value matches the expected type. Returns result on violation."""
    t = schema.type
    if t is None:
        return None  # no type constraint

    if t == "string":
        if not isinstance(value, str):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected string, got {type(value).__name__}",
            )
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int) or isinstance(value, float):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected integer, got {type(value).__name__}",
            )
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected number, got {type(value).__name__}",
            )
    elif t == "boolean":
        if not isinstance(value, bool):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected boolean, got {type(value).__name__}",
            )
    elif t == "array":
        if not isinstance(value, list):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected array, got {type(value).__name__}",
            )
    elif t == "object":
        if not isinstance(value, dict):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["type"],
                detail=f"expected object, got {type(value).__name__}",
            )

    return None


# ── Numeric constraints ─────────────────────────────────────────────────────


def _check_numeric(value: int | float, schema: ApiSchema) -> ConstraintCheckResult | None:
    """Check minimum, maximum, exclusiveMinimum, exclusiveMaximum."""
    if schema.minimum is not None:
        if schema.exclusive_minimum:
            if value <= schema.minimum:
                return ConstraintCheckResult(
                    status="violates",
                    violated_constraints=["exclusiveMinimum"],
                    detail=f"expected > {schema.minimum}, got {value}",
                )
        else:
            if value < schema.minimum:
                return ConstraintCheckResult(
                    status="violates",
                    violated_constraints=["minimum"],
                    detail=f"expected >= {schema.minimum}, got {value}",
                )

    if schema.maximum is not None:
        if schema.exclusive_maximum:
            if value >= schema.maximum:
                return ConstraintCheckResult(
                    status="violates",
                    violated_constraints=["exclusiveMaximum"],
                    detail=f"expected < {schema.maximum}, got {value}",
                )
        else:
            if value > schema.maximum:
                return ConstraintCheckResult(
                    status="violates",
                    violated_constraints=["maximum"],
                    detail=f"expected <= {schema.maximum}, got {value}",
                )

    return None


# ── String constraints ──────────────────────────────────────────────────────


def _check_string(value: str, schema: ApiSchema) -> ConstraintCheckResult | None:
    """Check minLength, maxLength, pattern, format."""
    if schema.min_length is not None and len(value) < schema.min_length:
        return ConstraintCheckResult(
            status="violates",
            violated_constraints=["minLength"],
            detail=f"minLength={schema.min_length}, got len={len(value)}",
        )

    if schema.max_length is not None and len(value) > schema.max_length:
        return ConstraintCheckResult(
            status="violates",
            violated_constraints=["maxLength"],
            detail=f"maxLength={schema.max_length}, got len={len(value)}",
        )

    if schema.pattern is not None:
        if not re.fullmatch(schema.pattern, value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["pattern"],
                detail=f"pattern '{schema.pattern}' not matched by {value!r}",
            )

    if schema.format:
        fmt_result = _check_format(value, schema.format)
        if fmt_result is not None:
            return fmt_result

    return None


# ── Format validation ───────────────────────────────────────────────────────

# Supported formats with deterministic validators.
# Unsupported formats return None (cannot determine → not executable).

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
)
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*:")


def _check_format(value: str, fmt: str) -> ConstraintCheckResult | None:
    """Check a single format constraint.

    Returns:
      - ConstraintCheckResult(status="violates") on proven violation
      - None when the value is valid (caller treats as pass-through)
      - ConstraintCheckResult(status="cannot_determine") for unsupported formats
    """
    if fmt == "email":
        if not _EMAIL_RE.match(value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:email"],
                detail=f"invalid email format: {value!r}",
            )
        return None  # valid
    elif fmt == "uuid":
        if not _UUID_RE.match(value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:uuid"],
                detail=f"invalid uuid format: {value!r}",
            )
        return None  # valid
    elif fmt == "date":
        if not _DATE_RE.match(value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:date"],
                detail=f"invalid date format: {value!r}",
            )
        return None  # valid
    elif fmt == "date-time":
        if not _DATETIME_RE.match(value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:date-time"],
                detail=f"invalid date-time format: {value!r}",
            )
        return None  # valid
    elif fmt == "ipv4":
        try:
            ipaddress.IPv4Address(value)
        except (ValueError, TypeError):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:ipv4"],
                detail=f"invalid ipv4 address: {value!r}",
            )
        return None  # valid
    elif fmt == "ipv6":
        try:
            ipaddress.IPv6Address(value)
        except (ValueError, TypeError):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:ipv6"],
                detail=f"invalid ipv6 address: {value!r}",
            )
        return None  # valid
    elif fmt == "hostname":
        if not _HOSTNAME_RE.match(value) or len(value) > 253:
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=["format:hostname"],
                detail=f"invalid hostname: {value!r}",
            )
        return None  # valid
    elif fmt in ("uri", "url"):
        if not _URI_RE.match(value):
            return ConstraintCheckResult(
                status="violates",
                violated_constraints=[f"format:{fmt}"],
                detail=f"invalid {fmt}: {value!r}",
            )
        return None  # valid
    else:
        # Unsupported format — cannot determine validity
        return ConstraintCheckResult(
            status="cannot_determine",
            detail=f"unsupported format '{fmt}' — cannot determine validity",
        )
