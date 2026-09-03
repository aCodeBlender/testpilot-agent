"""Tests for schema_validator — T0205."""

import pytest

from testpilot.domain.schema import ApiSchema
from testpilot.validator.schema_validator import validate_schema


# ── Type checks ─────────────────────────────────────────────────────────────


class TestTypes:
    def test_string_valid(self):
        assert validate_schema("hello", ApiSchema(type="string")) is None

    def test_string_invalid(self):
        assert validate_schema(123, ApiSchema(type="string")) is not None

    def test_integer_valid(self):
        assert validate_schema(42, ApiSchema(type="integer")) is None

    def test_integer_rejects_bool(self):
        """bool is subclass of int in Python — must be rejected."""
        assert validate_schema(True, ApiSchema(type="integer")) is not None

    def test_integer_rejects_float(self):
        assert validate_schema(3.14, ApiSchema(type="integer")) is not None

    def test_number_int_valid(self):
        assert validate_schema(42, ApiSchema(type="number")) is None

    def test_number_float_valid(self):
        assert validate_schema(3.14, ApiSchema(type="number")) is None

    def test_number_rejects_bool(self):
        assert validate_schema(True, ApiSchema(type="number")) is not None

    def test_number_rejects_string(self):
        assert validate_schema("3.14", ApiSchema(type="number")) is not None

    def test_boolean_valid(self):
        assert validate_schema(True, ApiSchema(type="boolean")) is None

    def test_boolean_invalid(self):
        assert validate_schema(1, ApiSchema(type="boolean")) is not None

    def test_object_valid(self):
        assert validate_schema({"a": 1}, ApiSchema(type="object")) is None

    def test_object_invalid(self):
        assert validate_schema([1], ApiSchema(type="object")) is not None

    def test_array_valid(self):
        assert validate_schema([1, 2], ApiSchema(type="array")) is None

    def test_array_invalid(self):
        assert validate_schema("not", ApiSchema(type="array")) is not None

    def test_null_valid(self):
        assert validate_schema(None, ApiSchema(type="null")) is None

    def test_null_invalid(self):
        assert validate_schema(1, ApiSchema(type="null")) is not None


# ── Nullable ────────────────────────────────────────────────────────────────


class TestNullable:
    def test_nullable_none_passes(self):
        assert validate_schema(None, ApiSchema(type="string", nullable=True)) is None

    def test_non_nullable_none_fails(self):
        assert validate_schema(None, ApiSchema(type="string", nullable=False)) is not None

    def test_nullable_value_still_validated(self):
        assert validate_schema("hello", ApiSchema(type="string", nullable=True)) is None


# ── Enum ────────────────────────────────────────────────────────────────────


class TestEnum:
    def test_enum_valid(self):
        assert validate_schema("a", ApiSchema(type="string", enum=["a", "b"])) is None

    def test_enum_invalid(self):
        assert validate_schema("c", ApiSchema(type="string", enum=["a", "b"])) is not None

    def test_enum_integer(self):
        assert validate_schema(1, ApiSchema(type="integer", enum=[1, 2, 3])) is None


# ── Object ──────────────────────────────────────────────────────────────────


class TestObject:
    def test_required_property_missing(self):
        schema = ApiSchema(type="object", required=["name"], properties={"name": ApiSchema(type="string")})
        assert validate_schema({}, schema) is not None

    def test_required_property_present(self):
        schema = ApiSchema(type="object", required=["name"], properties={"name": ApiSchema(type="string")})
        assert validate_schema({"name": "Alice"}, schema) is None

    def test_additional_properties_false(self):
        schema = ApiSchema(type="object", properties={"name": ApiSchema(type="string")}, additional_properties=False)
        assert validate_schema({"name": "Alice", "extra": 1}, schema) is not None

    def test_additional_properties_true(self):
        schema = ApiSchema(type="object", properties={"name": ApiSchema(type="string")}, additional_properties=True)
        assert validate_schema({"name": "Alice", "extra": 1}, schema) is None

    def test_additional_properties_none(self):
        schema = ApiSchema(type="object", properties={"name": ApiSchema(type="string")})
        assert validate_schema({"name": "Alice", "extra": 1}, schema) is None

    def test_additional_properties_schema_valid(self):
        """additionalProperties as ApiSchema — extra must match the schema."""
        schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
            additional_properties=ApiSchema(type="integer"),
        )
        assert validate_schema({"name": "Alice", "count": 5}, schema) is None

    def test_additional_properties_schema_invalid(self):
        """additionalProperties as ApiSchema — extra that doesn't match fails."""
        schema = ApiSchema(
            type="object",
            properties={"name": ApiSchema(type="string")},
            additional_properties=ApiSchema(type="integer"),
        )
        assert validate_schema({"name": "Alice", "count": "five"}, schema) is not None

    def test_nested_object(self):
        schema = ApiSchema(
            type="object",
            properties={
                "profile": ApiSchema(
                    type="object",
                    required=["email"],
                    properties={"email": ApiSchema(type="string")},
                ),
            },
        )
        assert validate_schema({"profile": {"email": "a@b.com"}}, schema) is None
        assert validate_schema({"profile": {}}, schema) is not None


# ── Array ───────────────────────────────────────────────────────────────────


class TestArray:
    def test_min_items(self):
        assert validate_schema([1, 2], ApiSchema(type="array", min_items=2)) is None
        assert validate_schema([1], ApiSchema(type="array", min_items=2)) is not None

    def test_max_items(self):
        assert validate_schema([1], ApiSchema(type="array", max_items=2)) is None
        assert validate_schema([1, 2, 3], ApiSchema(type="array", max_items=2)) is not None

    def test_unique_items(self):
        assert validate_schema([1, 2, 3], ApiSchema(type="array", unique_items=True)) is None
        assert validate_schema([1, 1, 2], ApiSchema(type="array", unique_items=True)) is not None

    def test_items_schema(self):
        schema = ApiSchema(type="array", items=ApiSchema(type="integer"))
        assert validate_schema([1, 2, 3], schema) is None
        assert validate_schema([1, "a", 3], schema) is not None


# ── String ──────────────────────────────────────────────────────────────────


class TestString:
    def test_min_length(self):
        assert validate_schema("abc", ApiSchema(type="string", min_length=3)) is None
        assert validate_schema("ab", ApiSchema(type="string", min_length=3)) is not None

    def test_max_length(self):
        assert validate_schema("ab", ApiSchema(type="string", max_length=3)) is None
        assert validate_schema("abcd", ApiSchema(type="string", max_length=3)) is not None

    def test_pattern(self):
        assert validate_schema("abc", ApiSchema(type="string", pattern=r"^[a-z]+$")) is None
        assert validate_schema("ABC", ApiSchema(type="string", pattern=r"^[a-z]+$")) is not None

    def test_pattern_search_not_fullmatch(self):
        """Pattern uses re.search — match anywhere in the string."""
        assert validate_schema("hello123world", ApiSchema(type="string", pattern=r"\d+")) is None
        assert validate_schema("no-digits", ApiSchema(type="string", pattern=r"\d+")) is not None


# ── Numeric constraints ─────────────────────────────────────────────────────


class TestNumeric:
    def test_minimum_inclusive(self):
        assert validate_schema(5, ApiSchema(type="integer", minimum=5)) is None
        assert validate_schema(4, ApiSchema(type="integer", minimum=5)) is not None

    def test_minimum_exclusive(self):
        assert validate_schema(6, ApiSchema(type="integer", minimum=5, exclusive_minimum=True)) is None
        assert validate_schema(5, ApiSchema(type="integer", minimum=5, exclusive_minimum=True)) is not None

    def test_maximum_inclusive(self):
        assert validate_schema(5, ApiSchema(type="integer", maximum=5)) is None
        assert validate_schema(6, ApiSchema(type="integer", maximum=5)) is not None

    def test_maximum_exclusive(self):
        assert validate_schema(4, ApiSchema(type="integer", maximum=5, exclusive_maximum=True)) is None
        assert validate_schema(5, ApiSchema(type="integer", maximum=5, exclusive_maximum=True)) is not None

    def test_multiple_of(self):
        assert validate_schema(10, ApiSchema(type="integer", multiple_of=5)) is None
        assert validate_schema(11, ApiSchema(type="integer", multiple_of=5)) is not None

    def test_multiple_of_float(self):
        assert validate_schema(1.5, ApiSchema(type="number", multiple_of=0.5)) is None
        assert validate_schema(1.3, ApiSchema(type="number", multiple_of=0.5)) is not None


# ── writeOnly response semantics ─────────────────────────────────────────────


class TestWriteOnlyResponse:
    """writeOnly required fields must NOT cause response validation failure."""

    def _password_schema(self) -> ApiSchema:
        """Schema with writeOnly 'password' required alongside 'name'."""
        return ApiSchema(
            type="object",
            properties={
                "name": ApiSchema(type="string"),
                "password": ApiSchema(type="string", write_only=True),
            },
            required=["name", "password"],
        )

    def test_writeonly_present_in_response_passes(self):
        """Response includes writeOnly field — always valid."""
        schema = self._password_schema()
        assert validate_schema({"name": "Alice", "password": "secret"}, schema, direction="response") is None

    def test_writeonly_absent_in_response_passes(self):
        """Response omits writeOnly field — must pass (direction=response)."""
        schema = self._password_schema()
        assert validate_schema({"name": "Alice"}, schema, direction="response") is None

    def test_writeonly_absent_in_request_fails(self):
        """Request omits writeOnly field — must fail (direction=request, default)."""
        schema = self._password_schema()
        err = validate_schema({"name": "Alice"}, schema)
        assert err is not None
        assert "password" in err

    def test_writeonly_absent_in_response_direction_default_fails(self):
        """Default direction=request — writeOnly absent → fail."""
        schema = self._password_schema()
        err = validate_schema({"name": "Alice"}, schema, direction="request")
        assert err is not None
        assert "password" in err

    def test_non_writeonly_absent_in_response_still_fails(self):
        """Non-writeOnly required field absent in response → still fails."""
        schema = self._password_schema()
        err = validate_schema({"password": "secret"}, schema, direction="response")
        assert err is not None
        assert "name" in err
