"""Tests for T0103-T0107: Domain model definitions + Code Review fixes."""

import pytest
from pydantic import ValidationError

from testpilot.config import AppConfig
from testpilot.domain.spec import ApiSpec, ApiEndpoint
from testpilot.domain.schema import (
    ApiSchema,
    ApiParameter,
    ApiRequestBody,
    ApiResponse,
    HttpMethod,
    ParameterLocation,
)


# ── T0103: AppConfig ────────────────────────────────────────────────────────

class TestAppConfig:
    def test_minimal_config(self):
        cfg = AppConfig(
            openapi_source="http://localhost:8080/v3/api-docs",
            target_base_url="http://localhost:8080",
        )
        assert cfg.openapi_source == "http://localhost:8080/v3/api-docs"
        assert cfg.target_base_url == "http://localhost:8080"
        assert cfg.bearer_token is None
        assert cfg.custom_headers == {}
        assert cfg.timeout_seconds == 30

    def test_full_config(self):
        cfg = AppConfig(
            openapi_source="./spec.yaml",
            target_base_url="http://staging:9090",
            bearer_token="tok123",
            custom_headers={"X-Custom": "val"},
            include_tags=["users"],
            exclude_tags=["admin"],
            max_cases_per_endpoint=5,
            timeout_seconds=10,
        )
        assert cfg.bearer_token == "tok123"
        assert cfg.custom_headers["X-Custom"] == "val"
        assert cfg.include_tags == ["users"]
        assert cfg.max_cases_per_endpoint == 5

    def test_serialization_roundtrip(self):
        cfg = AppConfig(
            openapi_source="spec.yaml",
            target_base_url="http://localhost:8080",
        )
        data = cfg.model_dump()
        restored = AppConfig.model_validate(data)
        assert restored == cfg

    def test_config_does_not_contain_api_metadata(self):
        """AppConfig must not have fields that belong in ApiSpec."""
        cfg = AppConfig(
            openapi_source="spec.yaml",
            target_base_url="http://localhost:8080",
        )
        assert not hasattr(cfg, "title")
        assert not hasattr(cfg, "servers")
        assert not hasattr(cfg, "endpoints")

    def test_no_llm_fields(self):
        """AppConfig must not contain LLM configuration (Phase 3 concern)."""
        cfg = AppConfig(
            openapi_source="spec.yaml",
            target_base_url="http://localhost:8080",
        )
        assert not hasattr(cfg, "llm_api_key")
        assert not hasattr(cfg, "llm_base_url")
        assert not hasattr(cfg, "llm_model")


# ── T0107: ApiSchema ────────────────────────────────────────────────────────

class TestApiSchema:
    def test_empty_schema(self):
        s = ApiSchema()
        assert s.type is None
        assert s.properties is None
        assert s.items is None
        assert s.required == []
        assert s.nullable is False

    def test_string_schema(self):
        s = ApiSchema(
            type="string",
            min_length=1,
            max_length=100,
            pattern="^[a-z]+$",
        )
        assert s.type == "string"
        assert s.min_length == 1
        assert s.max_length == 100
        assert s.pattern == "^[a-z]+$"

    def test_integer_schema(self):
        s = ApiSchema(type="integer", minimum=0, maximum=150)
        assert s.type == "integer"
        assert s.minimum == 0
        assert s.maximum == 150

    def test_array_schema(self):
        s = ApiSchema(
            type="array",
            items=ApiSchema(type="string"),
            min_items=1,
            max_items=10,
        )
        assert s.type == "array"
        assert s.items is not None
        assert s.items.type == "string"
        assert s.min_items == 1

    def test_object_schema_recursive(self):
        s = ApiSchema(
            type="object",
            properties={
                "name": ApiSchema(type="string"),
                "age": ApiSchema(type="integer", minimum=0),
                "address": ApiSchema(
                    type="object",
                    properties={
                        "city": ApiSchema(type="string"),
                    },
                ),
            },
            required=["name"],
        )
        assert s.type == "object"
        assert "name" in s.properties
        assert "city" in s.properties["address"].properties
        assert s.required == ["name"]

    def test_enum(self):
        s = ApiSchema(type="string", enum=["active", "inactive"])
        assert s.enum == ["active", "inactive"]

    def test_nullable(self):
        s = ApiSchema(type="string", nullable=True)
        assert s.nullable is True

    def test_example_and_default(self):
        s = ApiSchema(type="string", example="hello", default="world")
        assert s.example == "hello"
        assert s.default == "world"

    def test_serialization_roundtrip(self):
        s = ApiSchema(
            type="object",
            properties={
                "id": ApiSchema(type="integer"),
                "name": ApiSchema(type="string", min_length=1),
            },
            required=["id"],
        )
        data = s.model_dump()
        restored = ApiSchema.model_validate(data)
        assert restored == s


# ── T0106: ApiParameter ─────────────────────────────────────────────────────

class TestApiParameter:
    def test_path_parameter(self):
        p = ApiParameter(
            name="id",
            location="path",
            required=True,
            param_schema=ApiSchema(type="integer"),
        )
        assert p.name == "id"
        assert p.location == "path"
        assert p.required is True
        assert p.param_schema.type == "integer"

    def test_query_parameter_optional(self):
        p = ApiParameter(
            name="page",
            location="query",
            param_schema=ApiSchema(type="integer", default=1),
        )
        assert p.required is False
        assert p.location == "query"

    def test_header_parameter(self):
        p = ApiParameter(
            name="X-Request-Id",
            location="header",
            required=False,
            param_schema=ApiSchema(type="string", format="uuid"),
        )
        assert p.location == "header"
        assert p.param_schema.format == "uuid"


# ── T0107: ApiRequestBody ───────────────────────────────────────────────────

class TestApiRequestBody:
    def test_json_body(self):
        body = ApiRequestBody(
            required=True,
            content_type="application/json",
            body_schema=ApiSchema(
                type="object",
                properties={
                    "name": ApiSchema(type="string"),
                    "email": ApiSchema(type="string", format="email"),
                },
                required=["name", "email"],
            ),
        )
        assert body.required is True
        assert body.content_type == "application/json"
        assert "name" in body.body_schema.properties

    def test_optional_body(self):
        body = ApiRequestBody(
            required=False,
            content_type="application/json",
            body_schema=ApiSchema(type="object"),
        )
        assert body.required is False


# ── T0107: ApiResponse (status_code removed) ───────────────────────────────

class TestApiResponse:
    def test_success_response(self):
        """Status code lives in the dict key, not inside ApiResponse."""
        resp = ApiResponse(
            description="Successful response",
            content_schema=ApiSchema(
                type="object",
                properties={"id": ApiSchema(type="integer")},
            ),
        )
        assert resp.description == "Successful response"
        assert resp.content_schema is not None

    def test_no_content_response(self):
        resp = ApiResponse(description="No content")
        assert resp.content_schema is None

    def test_error_response(self):
        resp = ApiResponse(
            description="Client error",
            content_schema=ApiSchema(
                type="object",
                properties={
                    "error": ApiSchema(type="string"),
                    "message": ApiSchema(type="string"),
                },
            ),
        )
        assert resp.description == "Client error"

    def test_no_status_code_field(self):
        """ApiResponse must not carry a status_code field."""
        resp = ApiResponse(description="test")
        assert not hasattr(resp, "status_code")


# ── T0104/T0105: ApiEndpoint ────────────────────────────────────────────────

class TestApiEndpoint:
    def test_minimal_endpoint(self):
        ep = ApiEndpoint(
            id="get_users",
            path="/users",
            method="GET",
        )
        assert ep.id == "get_users"
        assert ep.path == "/users"
        assert ep.method == "GET"
        assert ep.parameters == []
        assert ep.request_body is None
        assert ep.responses == {}

    def test_full_endpoint(self):
        ep = ApiEndpoint(
            id="create_user",
            path="/users",
            method="POST",
            operation_id="createUser",
            summary="Create a user",
            description="Creates a new user in the system",
            tags=["users"],
            parameters=[
                ApiParameter(
                    name="X-Idempotency-Key",
                    location="header",
                    required=True,
                    param_schema=ApiSchema(type="string", format="uuid"),
                ),
            ],
            request_body=ApiRequestBody(
                required=True,
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                        "email": ApiSchema(type="string", format="email"),
                    },
                    required=["name", "email"],
                ),
            ),
            responses={
                "201": ApiResponse(
                    description="User created",
                    content_schema=ApiSchema(
                        type="object",
                        properties={"id": ApiSchema(type="integer")},
                    ),
                ),
                "400": ApiResponse(description="Bad request"),
            },
        )
        assert ep.operation_id == "createUser"
        assert ep.tags == ["users"]
        assert len(ep.parameters) == 1
        assert ep.request_body is not None
        assert "201" in ep.responses
        assert "400" in ep.responses

    def test_endpoint_with_path_params(self):
        ep = ApiEndpoint(
            id="get_user_by_id",
            path="/users/{id}",
            method="GET",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    required=True,
                    param_schema=ApiSchema(type="integer"),
                ),
            ],
        )
        assert ep.path == "/users/{id}"
        assert ep.parameters[0].name == "id"
        assert ep.parameters[0].location == "path"


# ── T0104: ApiSpec ──────────────────────────────────────────────────────────

class TestApiSpec:
    def test_minimal_spec(self):
        spec = ApiSpec(title="My API", version="1.0.0")
        assert spec.title == "My API"
        assert spec.version == "1.0.0"
        assert spec.servers == []
        assert spec.endpoints == []

    def test_spec_with_servers(self):
        spec = ApiSpec(
            title="Petstore",
            version="1.0.0",
            servers=["http://localhost:8080", "https://api.example.com"],
        )
        assert len(spec.servers) == 2
        assert spec.servers[0] == "http://localhost:8080"

    def test_spec_with_endpoints(self):
        spec = ApiSpec(
            title="Demo API",
            version="1.0.0",
            servers=["http://localhost:8080"],
            endpoints=[
                ApiEndpoint(id="list_users", path="/users", method="GET"),
                ApiEndpoint(
                    id="create_user",
                    path="/users",
                    method="POST",
                    request_body=ApiRequestBody(
                        required=True,
                        body_schema=ApiSchema(
                            type="object",
                            properties={"name": ApiSchema(type="string")},
                            required=["name"],
                        ),
                    ),
                ),
                ApiEndpoint(
                    id="get_user",
                    path="/users/{id}",
                    method="GET",
                    parameters=[
                        ApiParameter(
                            name="id",
                            location="path",
                            required=True,
                            param_schema=ApiSchema(type="integer"),
                        ),
                    ],
                ),
            ],
        )
        assert len(spec.endpoints) == 3
        assert spec.endpoints[0].method == "GET"
        assert spec.endpoints[1].request_body is not None
        assert spec.endpoints[2].parameters[0].name == "id"

    def test_spec_serialization_roundtrip(self):
        spec = ApiSpec(
            title="Test",
            version="0.1",
            endpoints=[
                ApiEndpoint(
                    id="ping",
                    path="/ping",
                    method="GET",
                    responses={
                        "200": ApiResponse(
                            content_schema=ApiSchema(type="string"),
                        ),
                    },
                ),
            ],
        )
        data = spec.model_dump()
        restored = ApiSpec.model_validate(data)
        assert restored == spec

    def test_spec_does_not_contain_runtime_info(self):
        """ApiSpec must not carry target_base_url or auth info."""
        spec = ApiSpec(title="X", version="1.0")
        assert not hasattr(spec, "target_base_url")
        assert not hasattr(spec, "bearer_token")
        assert not hasattr(spec, "timeout_seconds")


# ── Validation tests (Code Review #5) ───────────────────────────────────────

class TestValidation:
    def test_invalid_http_method_rejected(self):
        """ApiEndpoint.method must reject values outside HttpMethod Literal."""
        with pytest.raises(ValidationError):
            ApiEndpoint(id="bad", path="/x", method="banana")

    def test_lowercase_method_rejected(self):
        """Methods must be uppercase — lowercase is not in the Literal set."""
        with pytest.raises(ValidationError):
            ApiEndpoint(id="bad", path="/x", method="get")

    def test_invalid_parameter_location_rejected(self):
        """ApiParameter.location must reject values outside ParameterLocation."""
        with pytest.raises(ValidationError):
            ApiParameter(name="x", location="body")

    def test_invalid_parameter_location_rejected_other(self):
        """Any string not in the Literal set must fail."""
        with pytest.raises(ValidationError):
            ApiParameter(name="x", location="form")

    def test_max_cases_per_endpoint_must_be_positive(self):
        """max_cases_per_endpoint <= 0 must fail (ge=1 constraint)."""
        with pytest.raises(ValidationError):
            AppConfig(
                openapi_source="spec.yaml",
                target_base_url="http://localhost:8080",
                max_cases_per_endpoint=0,
            )

    def test_timeout_must_be_positive(self):
        """timeout_seconds <= 0 must fail (ge=1 constraint)."""
        with pytest.raises(ValidationError):
            AppConfig(
                openapi_source="spec.yaml",
                target_base_url="http://localhost:8080",
                timeout_seconds=-1,
            )

    def test_mutable_defaults_not_shared_between_instances(self):
        """list/dict fields must give each instance its own copy."""
        a = AppConfig(openapi_source="s", target_base_url="http://a")
        b = AppConfig(openapi_source="s", target_base_url="http://b")
        a.custom_headers["X-A"] = "1"
        a.include_tags.append("tag")
        assert b.custom_headers == {}
        assert b.include_tags == []

    def test_api_schema_mutable_defaults_not_shared(self):
        """ApiSchema list fields must not be shared across instances."""
        a = ApiSchema()
        b = ApiSchema()
        a.required.append("x")
        assert b.required == []

    def test_response_status_code_expressed_by_dict_key(self):
        """responses dict key is the sole source of status code."""
        spec = ApiSpec(
            title="T",
            version="1",
            endpoints=[
                ApiEndpoint(
                    id="e",
                    path="/x",
                    method="GET",
                    responses={
                        "200": ApiResponse(description="ok"),
                        "404": ApiResponse(description="not found"),
                    },
                ),
            ],
        )
        ep = spec.endpoints[0]
        assert set(ep.responses.keys()) == {"200", "404"}
        # ApiResponse itself has no status_code attribute
        for resp in ep.responses.values():
            assert not hasattr(resp, "status_code")
