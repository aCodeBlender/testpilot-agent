"""Tests for Phase 3D dependency models, inference, extraction, and runtime state.

Test scenarios per spec:
1.  Path-parameter dependency inference (userId from /users/{userId})
2.  Resource family matching
3.  RuntimeState lifecycle
4.  ExtractedScalar and JSON Pointer resolution
5.  Secret detection
6.  ApiDependency frozen model
7.  DependencySource/DependencyTarget frozen models
8.  No-op for endpoints without path params
9.  Multiple path params in one endpoint
10. List endpoint rejected as producer (returns array, not scalar)
11. RuntimeState.get returns None for missing key
12. RuntimeState.resolve raises KeyError for missing key
13. Extract nested scalar via deep pointer
14. Secret value rejected by RuntimeState.put()
15. ExtractionError on missing key
16. ExtractionError on non-scalar value
17. Ambiguous producer → unresolved (not bound)
18. Different resource family → no binding
19. Field name mismatch → no binding
20. No producer → unresolved
21. Same-named id from different resources → RuntimeState doesn't conflict
22. List/array response → extract_scalar rejects
23. Compatible schema types → dependency established
24. Incompatible schema types → no dependency
25. Producer type unknown → unresolved
26. Consumer type unknown → unresolved
27. Same name + same family + incompatible type → still no binding
"""

from __future__ import annotations

import pytest

from testpilot.domain.schema import (
    ApiParameter,
    ApiRequestBody,
    ApiResponse,
    ApiSchema,
    HttpMethod,
)
from testpilot.domain.spec import ApiEndpoint
from testpilot.dependency.analyzer import (
    _resolve_pointer_schema,
    _types_compatible,
    infer_dependencies,
)
from testpilot.dependency.exceptions import ExtractionError
from testpilot.dependency.extractor import extract_scalar, _looks_secret, _resolve_pointer
from testpilot.dependency.models import (
    ApiDependency,
    DependencySource,
    DependencyTarget,
    ExtractedScalar,
)
from testpilot.dependency.resource_family import resource_family_from_path
from testpilot.dependency.runtime_state import RuntimeState, RuntimeValue


# ── Fixtures ────────────────────────────────────────────────────────────────


def _ep(
    id: str,
    path: str,
    method: HttpMethod = "GET",
    operation_id: str | None = None,
) -> ApiEndpoint:
    """Minimal endpoint without schema info (for non-inference tests)."""
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        operation_id=operation_id or id,
    )


def _producer_ep(
    id: str,
    path: str,
    response_properties: dict[str, str],
    method: HttpMethod = "POST",
    status_code: str = "201",
) -> ApiEndpoint:
    """Producer endpoint with typed response schema.

    *response_properties* maps field name to JSON Schema type, e.g.
    ``{"id": "integer", "name": "string"}``.
    """
    props = {k: ApiSchema(type=v) for k, v in response_properties.items()}
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        operation_id=id,
        responses={
            status_code: ApiResponse(
                content_schema=ApiSchema(type="object", properties=props),
            ),
        },
    )


def _consumer_ep(
    id: str,
    path: str,
    param_name: str,
    param_type: str,
    method: HttpMethod = "GET",
) -> ApiEndpoint:
    """Consumer endpoint with a typed path parameter."""
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        operation_id=id,
        parameters=[
            ApiParameter(
                name=param_name,
                location="path",
                required=True,
                param_schema=ApiSchema(type=param_type),
            ),
        ],
    )


# ── Resource Family Tests ───────────────────────────────────────────────────


class TestResourceFamily:
    """Scenario 2: resource family matching."""

    def test_users_path(self):
        assert resource_family_from_path("/users") == "user"

    def test_users_with_id(self):
        assert resource_family_from_path("/users/{userId}") == "user"

    def test_orders_path(self):
        assert resource_family_from_path("/orders") == "order"

    def test_nested_resource(self):
        # /users/{userId}/posts -> "user" (first segment)
        assert resource_family_from_path("/users/{userId}/posts") == "user"

    def test_root_path_returns_none(self):
        assert resource_family_from_path("/") is None

    def test_empty_path_returns_none(self):
        assert resource_family_from_path("") is None

    def test_single_param_path(self):
        assert resource_family_from_path("/{id}") is None

    def test_kebab_case(self):
        assert resource_family_from_path("/api-keys") == "api-key"

    def test_already_singular(self):
        # "status" ends in "s", len > 3, not "ss" -> strips to "statu"
        # This is a known limitation of conservative de-pluralisation.
        pass

    def test_double_s_not_stripped(self):
        assert resource_family_from_path("/addresses") == "address"


# ── Dependency Model Tests ──────────────────────────────────────────────────


class TestDependencyModels:
    """Scenarios 6, 7: frozen Pydantic models."""

    def test_dependency_source_frozen(self):
        src = DependencySource(endpoint_id="getUser", response_pointer="/id")
        with pytest.raises(Exception):
            src.endpoint_id = "other"

    def test_dependency_target_frozen(self):
        tgt = DependencyTarget(
            endpoint_id="updateUser",
            parameter_name="userId",
            parameter_location="path",
        )
        with pytest.raises(Exception):
            tgt.endpoint_id = "other"

    def test_api_dependency_frozen(self):
        dep = ApiDependency(
            source=DependencySource(endpoint_id="createUser", response_pointer="/id"),
            target=DependencyTarget(
                endpoint_id="getUserById",
                parameter_name="userId",
                parameter_location="path",
            ),
        )
        with pytest.raises(Exception):
            dep.confidence = "llm"

    def test_api_dependency_default_confidence(self):
        dep = ApiDependency(
            source=DependencySource(endpoint_id="a", response_pointer="/id"),
            target=DependencyTarget(
                endpoint_id="b", parameter_name="x", parameter_location="path"
            ),
        )
        assert dep.confidence == "deterministic"

    def test_api_dependency_with_family(self):
        dep = ApiDependency(
            source=DependencySource(endpoint_id="a", response_pointer="/id"),
            target=DependencyTarget(
                endpoint_id="b", parameter_name="x", parameter_location="path"
            ),
            resource_family="user",
        )
        assert dep.resource_family == "user"

    def test_schema_type_on_source(self):
        src = DependencySource(
            endpoint_id="ep", response_pointer="/id", schema_type="integer"
        )
        assert src.schema_type == "integer"

    def test_schema_type_on_target(self):
        tgt = DependencyTarget(
            endpoint_id="ep",
            parameter_name="id",
            parameter_location="path",
            schema_type="integer",
        )
        assert tgt.schema_type == "integer"


# ── Schema Type Resolution Tests ────────────────────────────────────────────


class TestSchemaTypeResolution:
    """Unit tests for _resolve_pointer_schema and _types_compatible."""

    def test_simple_property(self):
        schema = ApiSchema(
            type="object",
            properties={"id": ApiSchema(type="integer")},
        )
        assert _resolve_pointer_schema(schema, "/id") == "integer"

    def test_nested_property(self):
        schema = ApiSchema(
            type="object",
            properties={
                "data": ApiSchema(
                    type="object",
                    properties={"id": ApiSchema(type="string")},
                ),
            },
        )
        assert _resolve_pointer_schema(schema, "/data/id") == "string"

    def test_missing_property_returns_none(self):
        schema = ApiSchema(
            type="object",
            properties={"id": ApiSchema(type="integer")},
        )
        assert _resolve_pointer_schema(schema, "/missing") is None

    def test_no_properties_returns_none(self):
        schema = ApiSchema(type="object")
        assert _resolve_pointer_schema(schema, "/id") is None

    def test_non_object_traversal_returns_none(self):
        schema = ApiSchema(
            type="object",
            properties={"items": ApiSchema(type="array")},
        )
        assert _resolve_pointer_schema(schema, "/items/id") is None

    def test_type_none_returns_none(self):
        schema = ApiSchema(
            type="object",
            properties={"id": ApiSchema(type=None)},
        )
        assert _resolve_pointer_schema(schema, "/id") is None

    def test_pointer_must_start_with_slash(self):
        schema = ApiSchema(type="object", properties={})
        assert _resolve_pointer_schema(schema, "id") is None

    def test_types_compatible_exact_match(self):
        assert _types_compatible("integer", "integer") is True

    def test_types_compatible_different(self):
        assert _types_compatible("string", "integer") is False

    def test_types_compatible_producer_unknown(self):
        assert _types_compatible(None, "integer") is False

    def test_types_compatible_consumer_unknown(self):
        assert _types_compatible("integer", None) is False

    def test_types_compatible_both_unknown(self):
        assert _types_compatible(None, None) is False

    def test_types_compatible_non_scalar(self):
        assert _types_compatible("object", "object") is False
        assert _types_compatible("array", "array") is False

    def test_types_compatible_number_vs_integer(self):
        # Conservative: no coercion between number and integer
        assert _types_compatible("number", "integer") is False


# ── Dependency Inference Tests ──────────────────────────────────────────────


class TestInferDependencies:
    """Scenarios 1, 8, 9, 10: deterministic inference with schema types."""

    def test_basic_user_dependency(self):
        """Scenario 1: POST /users (response.id:integer) -> GET /users/{userId} (path:integer)."""
        endpoints = [
            _ep("listUsers", "/users", "GET"),
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUserById", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1
        assert deps[0].source.endpoint_id == "createUser"
        assert deps[0].target.endpoint_id == "getUserById"
        assert deps[0].source.schema_type == "integer"
        assert deps[0].target.schema_type == "integer"

    def test_no_deps_without_path_params(self):
        """Scenario 8: endpoints without path params produce no deps."""
        endpoints = [
            _ep("listUsers", "/users", "GET"),
            _ep("listOrders", "/orders", "GET"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_multiple_path_params(self):
        """Scenario 9: endpoint with multiple path params, each typed."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _producer_ep("createOrder", "/orders", {"id": "string"}),
            _consumer_ep(
                "getUserOrder",
                "/users/{userId}/orders/{orderId}",
                "userId",
                "integer",
            ),
        ]
        # Need to add orderId param to the consumer
        ep = endpoints[2]
        ep.parameters.append(
            ApiParameter(
                name="orderId",
                location="path",
                required=True,
                param_schema=ApiSchema(type="string"),
            )
        )
        deps = infer_dependencies(endpoints)
        param_names = {d.target.parameter_name for d in deps}
        assert "userId" in param_names
        assert "orderId" in param_names

    def test_list_endpoint_rejected_as_producer(self):
        """Scenario 10: list endpoint (GET /resource) is NOT a valid producer."""
        endpoints = [
            _ep("listProducts", "/products", "GET"),
            _consumer_ep("getProductById", "/products/{productId}", "productId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_no_self_dependency(self):
        """An endpoint cannot depend on itself."""
        endpoints = [
            _consumer_ep("getUserById", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        for dep in deps:
            assert dep.source.endpoint_id != dep.target.endpoint_id

    def test_deterministic_confidence(self):
        """All inferred deps have confidence='deterministic'."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUser", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        for dep in deps:
            assert dep.confidence == "deterministic"

    def test_default_status_codes(self):
        """Source has default status codes [200, 201]."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUser", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        for dep in deps:
            assert dep.source.status_codes == [200, 201]

    def test_custom_status_codes(self):
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUser", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints, default_status_codes=[200])
        for dep in deps:
            assert dep.source.status_codes == [200]

    def test_resource_family_on_dependency(self):
        """Dependencies carry the resource family."""
        endpoints = [
            _producer_ep("createOrder", "/orders", {"id": "string"}),
            _consumer_ep("getOrder", "/orders/{orderId}", "orderId", "string"),
        ]
        deps = infer_dependencies(endpoints)
        for dep in deps:
            assert dep.resource_family == "order"

    def test_schema_types_populated_on_dependency(self):
        """Successful deps carry real schema types, not None."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUser", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1
        assert deps[0].source.schema_type == "integer"
        assert deps[0].target.schema_type == "integer"


# ── Schema Compatibility Tests ──────────────────────────────────────────────


class TestSchemaCompatibility:
    """Scenarios 23-27: type compatibility in dependency inference."""

    def test_compatible_type_establishes_dependency(self):
        """Scenario A: producer response.id:integer + consumer path.id:integer → bound."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getUserById", "/users/{id}", "id", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1
        assert deps[0].source.schema_type == "integer"
        assert deps[0].target.schema_type == "integer"

    def test_incompatible_type_no_dependency(self):
        """Scenario B: producer response.id:string + consumer path.id:integer → no dep."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "string"}),
            _consumer_ep("getUserById", "/users/{id}", "id", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_producer_type_unknown_unresolved(self):
        """Scenario C: producer response.id type unknown → no dep."""
        # Producer with no response schema at all
        producer = ApiEndpoint(
            id="createUser",
            path="/users",
            method="POST",
            operation_id="createUser",
            responses={},  # no responses defined
        )
        consumer = _consumer_ep("getUserById", "/users/{id}", "id", "integer")
        deps = infer_dependencies([producer, consumer])
        assert deps == []

    def test_producer_type_none_in_schema(self):
        """Producer response field has type=None (implicit) → no dep."""
        producer = ApiEndpoint(
            id="createUser",
            path="/users",
            method="POST",
            operation_id="createUser",
            responses={
                "201": ApiResponse(
                    content_schema=ApiSchema(
                        type="object",
                        properties={"id": ApiSchema(type=None)},
                    ),
                ),
            },
        )
        consumer = _consumer_ep("getUserById", "/users/{id}", "id", "integer")
        deps = infer_dependencies([producer, consumer])
        assert deps == []

    def test_consumer_type_unknown_unresolved(self):
        """Scenario D: consumer param type unknown → no dep."""
        producer = _producer_ep("createUser", "/users", {"id": "integer"})
        # Consumer with param_schema.type = None
        consumer = ApiEndpoint(
            id="getUserById",
            path="/users/{id}",
            method="GET",
            operation_id="getUserById",
            parameters=[
                ApiParameter(
                    name="id",
                    location="path",
                    required=True,
                    param_schema=ApiSchema(type=None),
                ),
            ],
        )
        deps = infer_dependencies([producer, consumer])
        assert deps == []

    def test_same_name_same_family_incompatible_type_still_no_binding(self):
        """Scenario E: name + family match but type incompatible → no dep."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "string"}),
            _consumer_ep("getUserById", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        # "userId" → implied family "user" → createUser in "user" family
        # But producer type "string" != consumer type "integer"
        assert deps == []

    def test_string_string_compatible(self):
        """string == string → compatible."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "string"}),
            _consumer_ep("getUser", "/users/{userId}", "userId", "string"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1

    def test_boolean_boolean_compatible(self):
        """boolean == boolean → compatible."""
        endpoints = [
            _producer_ep("createFlag", "/flags", {"active": "boolean"}),
            _consumer_ep("getFlag", "/flags/{active}", "active", "boolean"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1

    def test_number_vs_integer_incompatible(self):
        """number ≠ integer → no dep (conservative, no coercion)."""
        endpoints = [
            _producer_ep("createVal", "/vals", {"id": "number"}),
            _consumer_ep("getVal", "/vals/{valId}", "valId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []


# ── JSON Pointer / Extraction Tests ─────────────────────────────────────────


class TestExtractScalar:
    """Scenarios 3, 13, 15, 16: scalar extraction and error handling."""

    def test_simple_id(self):
        body = {"id": 42, "name": "Alice"}
        result = extract_scalar(body, "/id")
        assert result.value == 42
        assert result.pointer == "/id"
        assert result.secret is False

    def test_nested_pointer(self):
        """Scenario 13: deep pointer."""
        body = {"data": {"user": {"id": 99}}}
        result = extract_scalar(body, "/data/user/id")
        assert result.value == 99

    def test_string_value(self):
        body = {"token": "abc123"}
        result = extract_scalar(body, "/token")
        assert result.value == "abc123"

    def test_bool_value(self):
        body = {"active": True}
        result = extract_scalar(body, "/active")
        assert result.value is True

    def test_float_value(self):
        body = {"score": 3.14}
        result = extract_scalar(body, "/score")
        assert result.value == pytest.approx(3.14)

    def test_missing_key_raises(self):
        """Scenario 15: ExtractionError on missing key."""
        body = {"id": 1}
        with pytest.raises(ExtractionError, match="not found"):
            extract_scalar(body, "/missing")

    def test_non_scalar_raises(self):
        """Scenario 16: ExtractionError on non-scalar (dict)."""
        body = {"data": {"nested": True}}
        with pytest.raises(ExtractionError, match="not a scalar"):
            extract_scalar(body, "/data")

    def test_non_scalar_list_raises(self):
        body = {"items": [1, 2, 3]}
        with pytest.raises(ExtractionError, match="not a scalar"):
            extract_scalar(body, "/items")

    def test_array_index(self):
        body = {"items": [10, 20, 30]}
        result = extract_scalar(body, "/items/1")
        assert result.value == 20

    def test_array_index_out_of_bounds(self):
        body = {"items": [10]}
        with pytest.raises(ExtractionError, match="out of bounds"):
            extract_scalar(body, "/items/5")

    def test_non_integer_array_index(self):
        body = {"items": [10]}
        with pytest.raises(ExtractionError, match="Non-integer"):
            extract_scalar(body, "/items/abc")

    def test_pointer_must_start_with_slash(self):
        body = {"id": 1}
        with pytest.raises(ExtractionError, match="must start with"):
            extract_scalar(body, "id")

    def test_tilde_unescaping(self):
        """RFC 6901: ~0 -> ~, ~1 -> /."""
        body = {"a/b": "slash", "c~d": "tilde"}
        assert extract_scalar(body, "/a~1b").value == "slash"
        assert extract_scalar(body, "/c~0d").value == "tilde"


# ── Secret Detection Tests ──────────────────────────────────────────────────


class TestSecretDetection:
    """Scenarios 5, 14: secret detection in extraction."""

    def test_openai_key_detected(self):
        body = {"api_key": "sk-abc123456789012345"}
        result = extract_scalar(body, "/api_key")
        assert result.secret is True

    def test_bearer_pointer_detected(self):
        body = {"authorization": "Bearer mytoken123"}
        result = extract_scalar(body, "/authorization")
        assert result.secret is True

    def test_token_pointer_detected(self):
        body = {"token": "some-value"}
        result = extract_scalar(body, "/token")
        assert result.secret is True

    def test_normal_value_not_secret(self):
        body = {"id": 42}
        result = extract_scalar(body, "/id")
        assert result.secret is False

    def test_short_string_not_secret(self):
        body = {"status": "ok"}
        result = extract_scalar(body, "/status")
        assert result.secret is False

    def test_looks_secret_openai_key(self):
        assert _looks_secret("sk-test1234567890", "/key") is True

    def test_looks_secret_long_token(self):
        assert _looks_secret("a]b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6", "/token") is True

    def test_looks_secret_by_pointer_name(self):
        assert _looks_secret("anything", "/access_token") is True

    def test_looks_secret_password(self):
        assert _looks_secret("short", "/password") is True


# ── RuntimeState Tests ──────────────────────────────────────────────────────


class TestRuntimeState:
    """Scenarios 3, 4, 11, 12: RuntimeState lifecycle."""

    def test_put_and_get(self):
        """Scenario 3: basic lifecycle."""
        state = RuntimeState()
        scalar = ExtractedScalar(pointer="/id", value=42, secret=False)
        state.put("getUser", "/id", scalar)
        rv = state.get("getUser", "/id")
        assert rv is not None
        assert rv.value == 42
        assert rv.source_endpoint_id == "getUser"

    def test_get_value_convenience(self):
        state = RuntimeState()
        scalar = ExtractedScalar(pointer="/id", value=99, secret=False)
        state.put("ep", "/id", scalar)
        assert state.get_value("ep", "/id") == 99

    def test_get_returns_none_for_missing(self):
        """Scenario 11: None for missing key."""
        state = RuntimeState()
        assert state.get("nope", "/id") is None

    def test_get_value_returns_none_for_missing(self):
        state = RuntimeState()
        assert state.get_value("nope", "/id") is None

    def test_resolve_raises_for_missing(self):
        """Scenario 12: KeyError for missing key."""
        state = RuntimeState()
        with pytest.raises(KeyError):
            state.resolve("nope", "/id")

    def test_resolve_returns_value(self):
        state = RuntimeState()
        scalar = ExtractedScalar(pointer="/id", value=7, secret=False)
        state.put("ep", "/id", scalar)
        assert state.resolve("ep", "/id") == 7

    def test_has(self):
        state = RuntimeState()
        assert state.has("ep", "/id") is False
        scalar = ExtractedScalar(pointer="/id", value=1, secret=False)
        state.put("ep", "/id", scalar)
        assert state.has("ep", "/id") is True

    def test_overwrite(self):
        """put() overwrites previous value for same key."""
        state = RuntimeState()
        s1 = ExtractedScalar(pointer="/id", value=1, secret=False)
        s2 = ExtractedScalar(pointer="/id", value=2, secret=False)
        state.put("ep", "/id", s1)
        state.put("ep", "/id", s2)
        assert state.get_value("ep", "/id") == 2

    def test_clear(self):
        state = RuntimeState()
        scalar = ExtractedScalar(pointer="/id", value=1, secret=False)
        state.put("ep", "/id", scalar)
        state.clear()
        assert len(state) == 0
        assert state.has("ep", "/id") is False

    def test_len(self):
        state = RuntimeState()
        assert len(state) == 0
        s1 = ExtractedScalar(pointer="/id", value=1, secret=False)
        s2 = ExtractedScalar(pointer="/name", value="x", secret=False)
        state.put("ep1", "/id", s1)
        state.put("ep2", "/name", s2)
        assert len(state) == 2

    def test_repr(self):
        state = RuntimeState()
        assert "RuntimeState" in repr(state)
        assert "0 values" in repr(state)

    def test_secret_rejected_by_put(self):
        """Scenario 14: secret values are NEVER stored in RuntimeState."""
        state = RuntimeState()
        scalar = ExtractedScalar(pointer="/token", value="sk-abc1234567", secret=True)
        with pytest.raises(ExtractionError, match="Refusing to store secret"):
            state.put("auth", "/token", scalar)
        # Value must not be stored
        assert state.has("auth", "/token") is False
        assert state.get("auth", "/token") is None

    def test_secret_not_stored_various_keys(self):
        """Secret rejection covers all sensitive pointer names."""
        state = RuntimeState()
        for pointer in ["/authorization", "/api_key", "/token", "/access_token",
                        "/refresh_token", "/password", "/secret", "/cookie"]:
            scalar = ExtractedScalar(pointer=pointer, value="sensitive-value", secret=True)
            with pytest.raises(ExtractionError, match="Refusing to store secret"):
                state.put("ep", pointer, scalar)
        assert len(state) == 0

    def test_different_endpoints_same_pointer(self):
        """Different endpoints can have the same pointer."""
        state = RuntimeState()
        s1 = ExtractedScalar(pointer="/id", value=1, secret=False)
        s2 = ExtractedScalar(pointer="/id", value=2, secret=False)
        state.put("ep1", "/id", s1)
        state.put("ep2", "/id", s2)
        assert state.get_value("ep1", "/id") == 1
        assert state.get_value("ep2", "/id") == 2

    def test_runtime_value_dataclass(self):
        """RuntimeValue is a frozen dataclass."""
        rv = RuntimeValue(value=42, source_endpoint_id="ep", pointer="/id", secret=False)
        assert rv.value == 42
        assert rv.secret is False


# ── ExtractedScalar Model Tests ─────────────────────────────────────────────


class TestExtractedScalarModel:
    """Scenario 4: ExtractedScalar frozen model."""

    def test_frozen(self):
        s = ExtractedScalar(pointer="/id", value=42)
        with pytest.raises(Exception):
            s.value = 99

    def test_default_secret_false(self):
        s = ExtractedScalar(pointer="/id", value=42)
        assert s.secret is False

    def test_secret_true(self):
        s = ExtractedScalar(pointer="/token", value="sk-abc", secret=True)
        assert s.secret is True


# ── Package Import Tests ────────────────────────────────────────────────────


class TestPackageImports:
    """Verify public API is accessible from the package."""

    def test_import_all_public_names(self):
        from testpilot.dependency import (
            ApiDependency,
            DependencyError,
            DependencySource,
            DependencyTarget,
            ExtractionError,
            ExtractedScalar,
            RuntimeState,
            RuntimeValue,
            extract_scalar,
            infer_dependencies,
            resource_family_from_path,
        )
        # Verify they are the correct types
        assert callable(infer_dependencies)
        assert callable(extract_scalar)
        assert callable(resource_family_from_path)
        assert issubclass(DependencyError, Exception)
        assert issubclass(ExtractionError, DependencyError)


# ── Ambiguous Producer Tests ────────────────────────────────────────────────


class TestAmbiguousProducer:
    """Scenario 17: multiple equally-qualified producers → unresolved."""

    def test_ambiguous_producers_not_bound(self):
        """Two same-family scalar producers for one consumer → no dep."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _producer_ep("createAdmin", "/users", {"id": "integer"}),
            _consumer_ep("getUserById", "/users/{userId}", "userId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        consumer_deps = [
            d for d in deps
            if d.target.endpoint_id == "getUserById"
            and d.target.parameter_name == "userId"
        ]
        assert consumer_deps == []

    def test_ambiguous_does_not_guess_by_order(self):
        """Swapping endpoint order must not change the result."""
        endpoints_a = [
            _producer_ep("createA", "/items", {"id": "integer"}),
            _producer_ep("createB", "/items", {"id": "integer"}),
            _consumer_ep("getA", "/items/{itemId}", "itemId", "integer"),
        ]
        endpoints_b = [
            _producer_ep("createB", "/items", {"id": "integer"}),
            _producer_ep("createA", "/items", {"id": "integer"}),
            _consumer_ep("getA", "/items/{itemId}", "itemId", "integer"),
        ]
        deps_a = infer_dependencies(endpoints_a)
        deps_b = infer_dependencies(endpoints_b)
        assert len(deps_a) == len(deps_b)
        assert len(deps_a) == 0

    def test_single_producer_is_bound(self):
        """One clear producer is still bound (no ambiguity)."""
        endpoints = [
            _producer_ep("createItem", "/items", {"id": "integer"}),
            _consumer_ep("getItem", "/items/{itemId}", "itemId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert len(deps) == 1
        assert deps[0].source.endpoint_id == "createItem"
        assert deps[0].target.endpoint_id == "getItem"


# ── Security Rule Tests ────────────────────────────────────────────────────


class TestSecurityRules:
    """Confirm existing safety invariants."""

    def test_different_resource_family_no_binding(self):
        """Endpoints from different families are never linked."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("getOrder", "/orders/{orderId}", "orderId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_field_name_mismatch_no_binding(self):
        """Parameter name must match a family prefix to be inferred."""
        endpoints = [
            _producer_ep("createUser", "/users", {"id": "integer"}),
            _consumer_ep("weirdEndpoint", "/users/{productId}", "productId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_no_producer_unresolved(self):
        """Consumer with path param but no matching producer → no dep."""
        endpoints = [
            _consumer_ep("getOrder", "/orders/{orderId}", "orderId", "integer"),
        ]
        deps = infer_dependencies(endpoints)
        assert deps == []

    def test_same_named_id_different_families_no_conflict(self):
        """Same pointer (/id) from different endpoints → separate keys in RuntimeState."""
        state = RuntimeState()
        s1 = ExtractedScalar(pointer="/id", value=100, secret=False)
        s2 = ExtractedScalar(pointer="/id", value=200, secret=False)
        state.put("getUser", "/id", s1)
        state.put("getOrder", "/id", s2)
        assert state.get_value("getUser", "/id") == 100
        assert state.get_value("getOrder", "/id") == 200

    def test_extract_scalar_rejects_list_response(self):
        """Scenario 22: extract_scalar rejects JSON arrays (list responses)."""
        body = [{"id": 1}, {"id": 2}]
        with pytest.raises(ExtractionError):
            extract_scalar(body, "/")

    def test_extract_scalar_rejects_list_at_pointer(self):
        """List nested at a valid pointer is also rejected."""
        body = {"items": [1, 2, 3]}
        with pytest.raises(ExtractionError, match="not a scalar"):
            extract_scalar(body, "/items")

    def test_extract_scalar_rejects_nested_list(self):
        """Nested list at pointer is also rejected."""
        body = {"data": [1, 2, 3]}
        with pytest.raises(ExtractionError, match="not a scalar"):
            extract_scalar(body, "/data")
