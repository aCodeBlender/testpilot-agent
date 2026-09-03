"""OpenAPI spec domain models.

These models represent the *resolved* OpenAPI specification after $ref resolution.
They do NOT contain runtime/test-run information (that lives in AppConfig).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from testpilot.domain.schema import (
    ApiParameter,
    ApiRequestBody,
    ApiResponse,
    HttpMethod,
)


class ApiEndpoint(BaseModel):
    """A single API endpoint (method + path combination).

    ``id`` is a stable identifier derived from ``operationId`` or
    synthesised as ``{method}_{path}`` when no operationId is present.
    Downstream models (TestScenario, TestCase, …) reference endpoints by this id.
    """

    id: str = Field(
        description="Stable unique identifier for this endpoint (operationId or {method}_{path})",
    )
    path: str = Field(
        description="URL path template (e.g. /users/{id})",
    )
    method: HttpMethod = Field(
        description="HTTP method in uppercase (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS, TRACE)",
    )
    operation_id: str | None = Field(
        default=None,
        description="Original operationId from the OpenAPI spec",
    )
    summary: str | None = Field(default=None)
    description: str | None = Field(default=None)
    tags: list[str] = Field(
        default_factory=list,
        description="OpenAPI tags associated with this endpoint",
    )
    deprecated: bool = Field(default=False)
    parameters: list[ApiParameter] = Field(
        default_factory=list,
        description="Request parameters (path, query, header, cookie)",
    )
    request_body: ApiRequestBody | None = Field(
        default=None,
        description="Request body definition (None for methods without body)",
    )
    responses: dict[str, ApiResponse] = Field(
        default_factory=dict,
        description="Response definitions keyed by status code string",
    )


class ApiSpec(BaseModel):
    """Top-level representation of a resolved OpenAPI specification.

    ``servers`` stores the raw server URLs from the spec.
    The actual target URL for this test run lives in ``AppConfig.target_base_url``.
    """

    title: str = Field(description="API title from info.title")
    version: str = Field(description="API version from info.version")
    servers: list[str] = Field(
        default_factory=list,
        description="Server URLs from the OpenAPI spec (informational, not used for execution)",
    )
    endpoints: list[ApiEndpoint] = Field(
        default_factory=list,
        description="All parsed endpoints",
    )
