"""Tests for T0202: Test Case Generator."""

import pytest

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiSchema, ApiParameter, ApiRequestBody
from testpilot.domain.testing import TestScenario
from testpilot.generator.testcase_generator import generate_test_cases
from testpilot.generator.exceptions import TestCaseGeneratorError


# ── Helpers ──────────────────────────────────────────────────────────────────


def _endpoint(
    id: str = "ep-test",
    path: str = "/test",
    method: str = "GET",
    parameters: list[ApiParameter] | None = None,
    request_body: ApiRequestBody | None = None,
) -> ApiEndpoint:
    return ApiEndpoint(
        id=id,
        path=path,
        method=method,
        parameters=parameters or [],
        request_body=request_body,
    )


def _scenario(
    id: str = "sc-1",
    endpoint_id: str = "ep-test",
    category: str = "happy_path",
    target_location=None,
    target_path=None,
) -> TestScenario:
    return TestScenario(
        id=id,
        endpoint_id=endpoint_id,
        source="deterministic",
        category=category,
        name=f"Test {category}",
        target_location=target_location,
        target_path=target_path,
    )


# ── Happy path valid values ─────────────────────────────────────────────────


class TestHappyPathValues:
    def test_string_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="q", location="query", param_schema=ApiSchema(type="string")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert len(cases) == 1
        assert cases[0].query_params["q"] == "test"

    def test_integer_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="page", location="query", param_schema=ApiSchema(type="integer")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["page"] == "1"

    def test_boolean_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="active", location="query", param_schema=ApiSchema(type="boolean")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["active"] == "true"

    def test_header_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="X-Trace", location="header", param_schema=ApiSchema(type="string")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].headers["X-Trace"] == "test"

    def test_path_param(self):
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(name="id", location="path", param_schema=ApiSchema(type="integer")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].path_params["id"] == "1"

    def test_cookie_param(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="session", location="cookie", param_schema=ApiSchema(type="string")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].cookies["session"] == "test"

    def test_body_generated(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].body == {"name": "test"}


# ── String format ────────────────────────────────────────────────────────────


class TestStringFormat:
    def test_email_format(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="email", location="query", param_schema=ApiSchema(type="string", format="email")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["email"] == "test@example.com"

    def test_uuid_format(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="id", location="query", param_schema=ApiSchema(type="string", format="uuid")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["id"] == "00000000-0000-4000-8000-000000000000"

    def test_date_format(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="d", location="query", param_schema=ApiSchema(type="string", format="date")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["d"] == "2026-01-01"

    def test_datetime_format(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="ts", location="query", param_schema=ApiSchema(type="string", format="date-time")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["ts"] == "2026-01-01T00:00:00Z"

    def test_unknown_format_uses_plain_string(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="x", location="query", param_schema=ApiSchema(type="string", format="custom-format")),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["x"] == "test"

    def test_email_in_body(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "email": ApiSchema(type="string", format="email"),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].body["email"] == "test@example.com"


# ── String pattern ───────────────────────────────────────────────────────────


class TestStringPattern:
    def test_matching_pattern(self):
        """Pattern '^[a-z]+$' should match 'test'."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="code",
                    location="query",
                    param_schema=ApiSchema(type="string", pattern=r"^[a-z]+$"),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["code"] == "test"

    def test_unmatchable_pattern_raises_error(self):
        """Pattern that no fixed candidate can match must raise TestCaseGeneratorError."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(type="string", pattern=r"^[xyz]{50}$"),
                ),
            ]
        )
        with pytest.raises(TestCaseGeneratorError, match="Cannot deterministically"):
            generate_test_cases(ep, _scenario())


# ── Enum ─────────────────────────────────────────────────────────────────────


class TestEnum:
    def test_enum_uses_first_value(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="status",
                    location="query",
                    param_schema=ApiSchema(type="string", enum=["active", "inactive", "pending"]),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["status"] == "active"


# ── Constraints ──────────────────────────────────────────────────────────────


class TestConstraints:
    def test_minimum_respected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer", minimum=5),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["page"] == "5"

    def test_maximum_only(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(type="integer", maximum=100),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert int(cases[0].query_params["x"]) <= 100

    def test_minimum_and_maximum(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(type="integer", minimum=10, maximum=20),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        val = int(cases[0].query_params["x"])
        assert 10 <= val <= 20

    def test_exclusive_minimum_respected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="page",
                    location="query",
                    param_schema=ApiSchema(type="integer", minimum=0, exclusive_minimum=True),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["page"] == "1"

    def test_exclusive_maximum_respected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(type="integer", minimum=0, maximum=10, exclusive_maximum=True),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert int(cases[0].query_params["x"]) <= 9

    def test_minlength_respected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="name",
                    location="query",
                    param_schema=ApiSchema(type="string", min_length=8),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert len(cases[0].query_params["name"]) == 8

    def test_maxlength_respected(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="name",
                    location="query",
                    param_schema=ApiSchema(type="string", max_length=3),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert len(cases[0].query_params["name"]) <= 3

    def test_minlength_and_maxlength(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="name",
                    location="query",
                    param_schema=ApiSchema(type="string", min_length=3, max_length=10),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        val = cases[0].query_params["name"]
        assert 3 <= len(val) <= 10

    def test_multiple_of(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="qty",
                    location="query",
                    param_schema=ApiSchema(type="integer", minimum=1, multiple_of=5),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert int(cases[0].query_params["qty"]) % 5 == 0

    def test_array_min_items(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "tags": ApiSchema(type="array", items=ApiSchema(type="string"), min_items=3),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert len(cases[0].body["tags"]) == 3

    def test_array_max_items_zero(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "tags": ApiSchema(type="array", items=ApiSchema(type="string"), max_items=0),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].body["tags"] == []

    def test_array_min_and_max_items(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "tags": ApiSchema(type="array", items=ApiSchema(type="string"), min_items=2, max_items=5),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert 2 <= len(cases[0].body["tags"]) <= 5

    def test_example_takes_priority(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="id",
                    location="query",
                    param_schema=ApiSchema(type="integer", example=42),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["id"] == "42"

    def test_default_used(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="limit",
                    location="query",
                    param_schema=ApiSchema(type="integer", default=25),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].query_params["limit"] == "25"


# ── uniqueItems ──────────────────────────────────────────────────────────────


class TestUniqueItems:
    def test_unique_string_array(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "tags": ApiSchema(
                            type="array",
                            items=ApiSchema(type="string"),
                            min_items=3,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        tags = cases[0].body["tags"]
        assert len(tags) == 3
        assert len(set(tags)) == 3  # all distinct

    def test_unique_integer_array(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "ids": ApiSchema(
                            type="array",
                            items=ApiSchema(type="integer"),
                            min_items=3,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        ids = cases[0].body["ids"]
        assert ids == [1, 2, 3]

    def test_unique_number_array(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "scores": ApiSchema(
                            type="array",
                            items=ApiSchema(type="number"),
                            min_items=2,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        scores = cases[0].body["scores"]
        assert len(scores) == 2
        assert scores[0] != scores[1]

    def test_unique_boolean_max_2(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "flags": ApiSchema(
                            type="array",
                            items=ApiSchema(type="boolean"),
                            min_items=2,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert set(cases[0].body["flags"]) == {True, False}

    def test_unique_boolean_over_2_raises_error(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "flags": ApiSchema(
                            type="array",
                            items=ApiSchema(type="boolean"),
                            min_items=3,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        with pytest.raises(TestCaseGeneratorError, match="unique boolean"):
            generate_test_cases(ep, _scenario())

    def test_unique_object_raises_error(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "items": ApiSchema(
                            type="array",
                            items=ApiSchema(type="object"),
                            min_items=2,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        with pytest.raises(TestCaseGeneratorError, match="uniqueItems"):
            generate_test_cases(ep, _scenario())

    def test_unique_items_with_max_items(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "tags": ApiSchema(
                            type="array",
                            items=ApiSchema(type="string"),
                            min_items=2,
                            max_items=5,
                            unique_items=True,
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        tags = cases[0].body["tags"]
        assert len(tags) == 2  # min_items wins
        assert len(set(tags)) == 2


# ── Number exclusive bounds ──────────────────────────────────────────────────


class TestNumberExclusiveBounds:
    def test_both_exclusive(self):
        """exclusive_minimum=1.0, exclusive_maximum=1.5 → value must be > 1.0 and < 1.5."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(
                        type="number",
                        minimum=1.0,
                        exclusive_minimum=True,
                        maximum=1.5,
                        exclusive_maximum=True,
                    ),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        val = float(cases[0].query_params["x"])
        assert 1.0 < val < 1.5

    def test_exclusive_min_with_max(self):
        """exclusive_minimum=1.0, maximum=1.5 → value must be > 1.0 and <= 1.5."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(
                        type="number",
                        minimum=1.0,
                        exclusive_minimum=True,
                        maximum=1.5,
                    ),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        val = float(cases[0].query_params["x"])
        assert 1.0 < val <= 1.5

    def test_min_with_exclusive_max(self):
        """minimum=1.0, exclusive_maximum=1.5 → value must be >= 1.0 and < 1.5."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(
                        type="number",
                        minimum=1.0,
                        maximum=1.5,
                        exclusive_maximum=True,
                    ),
                ),
            ]
        )
        cases = generate_test_cases(ep, _scenario())
        val = float(cases[0].query_params["x"])
        assert 1.0 <= val < 1.5

    def test_both_exclusive_impossible_raises_error(self):
        """exclusive_minimum=1.5, exclusive_maximum=1.5 → no valid value."""
        ep = _endpoint(
            parameters=[
                ApiParameter(
                    name="x",
                    location="query",
                    param_schema=ApiSchema(
                        type="number",
                        minimum=1.5,
                        exclusive_minimum=True,
                        maximum=1.5,
                        exclusive_maximum=True,
                    ),
                ),
            ]
        )
        with pytest.raises(TestCaseGeneratorError, match="No valid number"):
            generate_test_cases(ep, _scenario())


# ── Nested object ────────────────────────────────────────────────────────────


class TestNestedObject:
    def test_nested_object_generated(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "profile": ApiSchema(
                            type="object",
                            properties={
                                "email": ApiSchema(type="string", format="email"),
                                "age": ApiSchema(type="integer"),
                            },
                        ),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert cases[0].body["profile"]["email"] == "test@example.com"
        assert cases[0].body["profile"]["age"] == 1


# ── read_only filtering ─────────────────────────────────────────────────────


class TestReadOnly:
    def test_read_only_excluded_from_body(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                        "id": ApiSchema(type="integer", read_only=True),
                    },
                ),
            ),
        )
        cases = generate_test_cases(ep, _scenario())
        assert "name" in cases[0].body
        assert "id" not in cases[0].body


# ── Mutations ────────────────────────────────────────────────────────────────


class TestMutations:
    def test_required_missing_deletes_field(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["name", "email"],
                    properties={
                        "name": ApiSchema(type="string"),
                        "email": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        sc = _scenario(category="required_missing", target_location="body", target_path="body.name")
        cases = generate_test_cases(ep, sc)
        assert "name" not in cases[0].body
        assert "email" in cases[0].body

    def test_required_missing_query(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="page", location="query", required=True, param_schema=ApiSchema(type="integer")),
                ApiParameter(name="limit", location="query", required=False, param_schema=ApiSchema(type="integer")),
            ]
        )
        sc = _scenario(category="required_missing", target_location="query", target_path="page")
        cases = generate_test_cases(ep, sc)
        assert "page" not in cases[0].query_params
        assert "limit" in cases[0].query_params

    def test_required_missing_cookie(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="session", location="cookie", required=True, param_schema=ApiSchema(type="string")),
            ]
        )
        sc = _scenario(category="required_missing", target_location="cookie", target_path="session")
        cases = generate_test_cases(ep, sc)
        assert "session" not in cases[0].cookies

    def test_null_mutation(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        sc = _scenario(category="null", target_location="body", target_path="body.name")
        cases = generate_test_cases(ep, sc)
        assert cases[0].body["name"] is None

    def test_null_cookie(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="session", location="cookie", param_schema=ApiSchema(type="string", nullable=False)),
            ]
        )
        sc = _scenario(category="null", target_location="cookie", target_path="session")
        cases = generate_test_cases(ep, sc)
        assert cases[0].cookies["session"] == "null"

    def test_wrong_type_mutation(self):
        ep = _endpoint(
            parameters=[
                ApiParameter(name="page", location="query", param_schema=ApiSchema(type="integer")),
            ]
        )
        sc = _scenario(category="wrong_type", target_location="query", target_path="page")
        cases = generate_test_cases(ep, sc)
        assert cases[0].query_params["page"] == "not-a-valid-value"

    def test_wrong_type_body_string_to_int(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    properties={
                        "name": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        sc = _scenario(category="wrong_type", target_location="body", target_path="body.name")
        cases = generate_test_cases(ep, sc)
        assert cases[0].body["name"] == 99999

    def test_wrong_type_path_param(self):
        """Path param wrong_type must actually mutate path_params."""
        ep = _endpoint(
            path="/users/{id}",
            parameters=[
                ApiParameter(name="id", location="path", param_schema=ApiSchema(type="integer")),
            ]
        )
        sc = _scenario(category="wrong_type", target_location="path", target_path="id")
        cases = generate_test_cases(ep, sc)
        assert cases[0].path_params["id"] == "not-a-valid-value"


# ── Guards ───────────────────────────────────────────────────────────────────


class TestGuards:
    def test_unsupported_category_raises_error(self):
        ep = _endpoint()
        sc = _scenario(category="empty_string")
        with pytest.raises(TestCaseGeneratorError, match="not yet implemented"):
            generate_test_cases(ep, sc)

    def test_endpoint_id_mismatch_raises_error(self):
        ep = _endpoint(id="ep-a")
        sc = _scenario(endpoint_id="ep-b")
        with pytest.raises(TestCaseGeneratorError, match="does not match"):
            generate_test_cases(ep, sc)


# ── Immutability ─────────────────────────────────────────────────────────────


class TestImmutability:
    def test_does_not_mutate_endpoint(self):
        ep = _endpoint(
            method="POST",
            request_body=ApiRequestBody(
                body_schema=ApiSchema(
                    type="object",
                    required=["name"],
                    properties={
                        "name": ApiSchema(type="string"),
                        "email": ApiSchema(type="string"),
                    },
                ),
            ),
        )
        orig_required = list(ep.request_body.body_schema.required)
        orig_props = set(ep.request_body.body_schema.properties.keys())

        sc = _scenario(category="required_missing", target_location="body", target_path="body.name")
        generate_test_cases(ep, sc)

        assert list(ep.request_body.body_schema.required) == orig_required
        assert set(ep.request_body.body_schema.properties.keys()) == orig_props
