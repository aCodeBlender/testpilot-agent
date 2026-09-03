"""Application configuration model.

AppConfig describes 'which environment to test this run'.
ApiSpec describes 'what the API is'.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Runtime configuration for a TestPilot run.

    This is intentionally separate from ApiSpec:
    - ApiSpec holds the OpenAPI spec metadata (servers, endpoints, etc.)
    - AppConfig holds the runtime choices (which server to hit, auth, filters)
    """

    # --- Required ---
    openapi_source: str = Field(
        description="OpenAPI spec URL or local file path"
    )
    target_base_url: str = Field(
        description="Actual base URL to send HTTP requests to (e.g. http://localhost:8080)"
    )

    # --- Auth ---
    bearer_token: str | None = Field(
        default=None,
        description="Bearer token for Authorization header",
    )
    custom_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional static headers to include in every request",
    )

    # --- Endpoint filters ---
    include_tags: list[str] = Field(
        default_factory=list,
        description="Only test endpoints with these tags (empty = all)",
    )
    exclude_tags: list[str] = Field(
        default_factory=list,
        description="Skip endpoints with these tags",
    )

    # --- Limits ---
    max_cases_per_endpoint: int = Field(
        default=20,
        ge=1,
        description="Maximum number of test cases to generate per endpoint",
    )

    # --- Execution ---
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        description="HTTP request timeout in seconds",
    )
