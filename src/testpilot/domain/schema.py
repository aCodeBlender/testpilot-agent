"""OpenAPI schema-related domain models.

These models represent the *resolved* OpenAPI structures after $ref resolution.
The actual resolution is handled by Prance (openapi/loader.py); these models
only hold the final, flattened representation that downstream modules consume.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Constrained type aliases ────────────────────────────────────────────────

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
"""Uppercase HTTP methods allowed by OpenAPI 3.x."""

ParameterLocation = Literal["path", "query", "header", "cookie"]
"""Where an ApiParameter appears in the HTTP request."""


class ApiSchema(BaseModel):
    """Simplified JSON Schema representation used across TestPilot.

    Recursive: ``items`` and ``properties`` reference the same type.
    This mirrors the structure Prance outputs after resolving ``$ref``.
    """

    type: str | None = Field(
        default=None,
        description="JSON Schema type (string, integer, number, boolean, array, object, null)",
    )
    format: str | None = Field(
        default=None,
        description="Format hint (date-time, email, uuid, int64, etc.)",
    )
    properties: dict[str, ApiSchema] | None = Field(
        default=None,
        description="Object properties (recursive)",
    )
    items: ApiSchema | None = Field(
        default=None,
        description="Array item schema (recursive)",
    )
    required: list[str] = Field(
        default_factory=list,
        description="List of required property names",
    )
    enum: list[Any] = Field(
        default_factory=list,
        description="Allowed enum values",
    )
    # --- Numeric constraints ---
    minimum: float | None = Field(default=None, description="Inclusive minimum")
    maximum: float | None = Field(default=None, description="Inclusive maximum")
    exclusive_minimum: bool = Field(default=False, description="OpenAPI 3.0.x: exclusiveMinimum is a boolean (true means minimum is exclusive)")
    exclusive_maximum: bool = Field(default=False, description="OpenAPI 3.0.x: exclusiveMaximum is a boolean (true means maximum is exclusive)")
    multiple_of: float | None = Field(default=None)
    # --- String constraints ---
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = Field(default=None, description="Regex pattern")
    # --- Array constraints ---
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=0)
    unique_items: bool | None = Field(default=None)
    # --- Object constraints ---
    additional_properties: bool | ApiSchema | None = Field(default=None)
    # --- Metadata ---
    nullable: bool = Field(default=False, description="Whether null is allowed")
    description: str | None = Field(default=None)
    example: Any | None = Field(default=None, description="Example value from spec")
    default: Any | None = Field(default=None, description="Default value from spec")
    read_only: bool = Field(default=False)
    write_only: bool = Field(default=False)


class ApiParameter(BaseModel):
    """A single request parameter (path, query, header, or cookie)."""

    name: str = Field(description="Parameter name")
    location: ParameterLocation = Field(
        description="Where the parameter appears: path, query, header, or cookie",
    )
    required: bool = Field(
        default=False,
        description="Whether this parameter is required",
    )
    deprecated: bool = Field(default=False)
    description: str | None = Field(default=None)
    param_schema: ApiSchema = Field(
        default_factory=ApiSchema,
        description="Schema describing the parameter value",
    )


class ApiRequestBody(BaseModel):
    """Request body definition for an endpoint."""

    required: bool = Field(
        default=False,
        description="Whether the request body is required",
    )
    content_type: str = Field(
        default="application/json",
        description="MIME type of the request body",
    )
    description: str | None = Field(default=None)
    body_schema: ApiSchema = Field(
        default_factory=ApiSchema,
        description="Schema describing the request body",
    )


class ApiResponse(BaseModel):
    """A single response definition.

    Instances are stored in ``ApiEndpoint.responses`` keyed by status code
    string (e.g. "200", "4XX", "default").  The status code is **not**
    duplicated inside the model — use the dict key to read it.
    """

    description: str | None = Field(default=None)
    content_schema: ApiSchema | None = Field(
        default=None,
        description="Schema of the response body (None if no body)",
    )
