"""Typed dependency models for Phase 3D.

These models represent *inferred* runtime-value dependencies between
API endpoints, derived deterministically from the OpenAPI spec structure
(no LLM involved).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DependencySource(BaseModel):
    """The producing endpoint and the JSON Pointer into its successful response."""

    model_config = ConfigDict(frozen=True)

    endpoint_id: str = Field(
        description="Endpoint id (from ApiEndpoint.id) that produces the value.",
    )
    response_pointer: str = Field(
        default="/id",
        description=(
            "RFC 6901 JSON Pointer into the 200/201 response body "
            '(e.g. "/id", "/data/id", "/token").'
        ),
    )
    status_codes: list[int] = Field(
        default_factory=lambda: [200, 201],
        description="Which success status codes make this extraction valid.",
    )
    schema_type: str | None = Field(
        default=None,
        description=(
            "JSON Schema type of the value at response_pointer "
            "(string, integer, number, boolean).  None when undetermined."
        ),
    )


class DependencyTarget(BaseModel):
    """The consuming endpoint and where the dependency value is injected."""

    model_config = ConfigDict(frozen=True)

    endpoint_id: str = Field(
        description="Endpoint id (from ApiEndpoint.id) that consumes the value.",
    )
    parameter_name: str = Field(
        description="Name of the path parameter, query parameter, or body field.",
    )
    parameter_location: Literal["path", "query", "body"] = Field(
        description="Where the parameter appears in the HTTP request.",
    )
    schema_type: str | None = Field(
        default=None,
        description=(
            "JSON Schema type of this parameter (string, integer, number, boolean)."
            "  None when undetermined."
        ),
    )


class ApiDependency(BaseModel):
    """One directed dependency edge: source produces a value that target consumes.

    ``confidence`` captures how the dependency was detected:
    - "deterministic": path-segment/resource-family structural match.
    - "llm": inferred by LLM (Phase 3D Batch 2).
    - "declared": user-supplied override.
    """

    model_config = ConfigDict(frozen=True)

    source: DependencySource = Field(description="Producer endpoint + response pointer.")
    target: DependencyTarget = Field(description="Consumer endpoint + injection point.")
    confidence: Literal["deterministic", "llm", "declared"] = Field(
        default="deterministic",
        description="How this dependency was detected.",
    )
    resource_family: str | None = Field(
        default=None,
        description="Resource-family slug for grouping (e.g. 'user', 'order').",
    )
    notes: str | None = Field(default=None, description="Free-form explanation.")


# ---------------------------------------------------------------------------
# Response extraction result
# ---------------------------------------------------------------------------


class ExtractedScalar(BaseModel):
    """A single scalar value extracted from an HTTP response."""

    model_config = ConfigDict(frozen=True)

    pointer: str = Field(description="The JSON Pointer used to locate this value.")
    value: Any = Field(description="The extracted scalar (str | int | float | bool).")
    secret: bool = Field(
        default=False,
        description="True if the value matched a secret-like pattern.",
    )
