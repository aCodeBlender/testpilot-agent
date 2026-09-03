"""Test Case Generator — T0202.

Input:  ApiEndpoint + TestScenario
Output: list[TestCase]

Constructs concrete HTTP request definitions (headers, query_params,
path_params, cookies, body) based on the scenario.  Does NOT send HTTP.

Value generation priority:
  OpenAPI example → OpenAPI default → deterministic type-based default
"""

from __future__ import annotations

import copy
import re
from typing import Any

from testpilot.domain.spec import ApiEndpoint
from testpilot.domain.schema import ApiSchema, ApiParameter
from testpilot.domain.testing import TestScenario, TestCase
from testpilot.generator.exceptions import TestCaseGeneratorError

# Categories the TestCaseGenerator can actually mutate.
_MUTABLE_CATEGORIES = frozenset({"happy_path", "required_missing", "null", "wrong_type"})


def generate_test_cases(
    endpoint: ApiEndpoint,
    scenario: TestScenario,
) -> list[TestCase]:
    """Generate one or more ``TestCase`` objects for the given scenario.

    Parameters
    ----------
    endpoint:
        The API endpoint being tested.
    scenario:
        The test scenario describing *what* to test.

    Returns
    -------
    list[TestCase]
        Typically one TestCase per scenario.

    Raises
    ------
    TestCaseGeneratorError
        If the scenario category is not yet supported for mutation,
        or if the scenario's endpoint_id does not match the endpoint.
    """
    # Guard: endpoint mismatch
    if scenario.endpoint_id != endpoint.id:
        raise TestCaseGeneratorError(
            f"Scenario endpoint_id '{scenario.endpoint_id}' does not match "
            f"endpoint id '{endpoint.id}'"
        )

    # Guard: unsupported mutation category
    if scenario.category not in _MUTABLE_CATEGORIES:
        raise TestCaseGeneratorError(
            f"Mutation category '{scenario.category}' is not yet implemented "
            f"in TestCaseGenerator"
        )

    # 1. Build a base valid request
    base = _build_base_request(endpoint)

    # 2. Apply mutation based on scenario
    mutated = _apply_mutation(base, scenario)

    # 3. Assemble TestCase
    return [TestCase(
        id=f"tc-{scenario.id}-1",
        endpoint_id=endpoint.id,
        scenario_id=scenario.id,
        method=endpoint.method,
        path=endpoint.path,
        headers=mutated.get("headers", {}),
        query_params=mutated.get("query_params", {}),
        path_params=mutated.get("path_params", {}),
        cookies=mutated.get("cookies", {}),
        body=mutated.get("body"),
    )]


# ── Base request construction ────────────────────────────────────────────────


def _build_base_request(endpoint: ApiEndpoint) -> dict[str, Any]:
    """Build a valid base request from endpoint definition."""
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}
    path_params: dict[str, str] = {}
    cookies: dict[str, str] = {}
    body: Any = None

    # Parameters
    for param in endpoint.parameters:
        value = _generate_value(param.param_schema)
        str_value = _to_string(value)
        if param.location == "query":
            query_params[param.name] = str_value
        elif param.location == "header":
            headers[param.name] = str_value
        elif param.location == "path":
            path_params[param.name] = str_value
        elif param.location == "cookie":
            cookies[param.name] = str_value

    # Request body
    if endpoint.request_body and endpoint.request_body.body_schema.type:
        body = _generate_value(endpoint.request_body.body_schema)
        # Filter out read_only properties from request body
        if isinstance(body, dict) and endpoint.request_body.body_schema.properties:
            body = _filter_read_only(body, endpoint.request_body.body_schema)
        headers["Content-Type"] = endpoint.request_body.content_type

    return {
        "headers": headers,
        "query_params": query_params,
        "path_params": path_params,
        "cookies": cookies,
        "body": body,
    }


def _filter_read_only(body: dict, schema: ApiSchema) -> dict:
    """Remove read_only properties from the generated body."""
    if not schema.properties:
        return body
    result = {}
    for prop_name, prop_schema in schema.properties.items():
        if prop_schema.read_only:
            continue
        val = body.get(prop_name)
        if isinstance(val, dict) and prop_schema.type == "object":
            result[prop_name] = _filter_read_only(val, prop_schema)
        else:
            result[prop_name] = val
    return result


# ── Deterministic value generation ───────────────────────────────────────────


def _generate_value(schema: ApiSchema) -> Any:
    """Generate a single deterministic value that satisfies *schema*.

    Priority: example → default → type-based.
    """
    if schema.example is not None:
        return copy.deepcopy(schema.example)

    if schema.default is not None:
        return copy.deepcopy(schema.default)

    if schema.enum:
        return copy.deepcopy(schema.enum[0])

    return _generate_by_type(schema)


def _generate_by_type(schema: ApiSchema) -> Any:
    """Generate a value based on the schema type."""
    t = schema.type

    if t == "string":
        return _generate_string(schema)
    elif t == "integer":
        return _generate_integer(schema)
    elif t == "number":
        return _generate_number(schema)
    elif t == "boolean":
        return True
    elif t == "array":
        return _generate_array(schema)
    elif t == "object":
        return _generate_object(schema)
    elif t == "null":
        return None
    else:
        return "test"


def _generate_string(schema: ApiSchema) -> str:
    """Generate a string respecting format, pattern, minLength, maxLength."""
    # Format-aware generation (deterministic, no Faker)
    if schema.format:
        formatted = _FORMAT_VALUES.get(schema.format)
        if formatted is not None:
            # Check if the formatted value satisfies length constraints
            min_len = schema.min_length or 0
            max_len = schema.max_length
            if len(formatted) >= min_len and (max_len is None or len(formatted) <= max_len):
                return formatted

    # Pattern-aware generation
    if schema.pattern:
        return _generate_string_for_pattern(schema)

    # Plain string with length constraints
    min_len = schema.min_length or 0
    max_len = schema.max_length

    base = "test"
    if min_len > len(base):
        base = "t" * min_len

    if max_len is not None and len(base) > max_len:
        base = base[:max_len]

    return base


# Deterministic format values (no randomness)
_FORMAT_VALUES: dict[str, str] = {
    "email": "test@example.com",
    "uuid": "00000000-0000-4000-8000-000000000000",
    "date": "2026-01-01",
    "date-time": "2026-01-01T00:00:00Z",
    "uri": "https://example.com",
    "url": "https://example.com",
    "hostname": "example.com",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
}


def _generate_string_for_pattern(schema: ApiSchema) -> str:
    """Try to generate a string matching the pattern.

    Attempts a small set of deterministic candidates.  If none match,
    raises TestCaseGeneratorError.
    """
    min_len = schema.min_length or 1
    max_len = schema.max_length
    pattern = schema.pattern

    # Build candidates
    candidates = ["test", "test123", "Test", "TEST"]
    # Pad candidates to meet min_length
    padded = []
    for c in candidates:
        if len(c) < min_len:
            c = c * ((min_len // len(c)) + 1)
            c = c[:min_len]
        if max_len is not None and len(c) > max_len:
            c = c[:max_len]
        padded.append(c)

    for candidate in padded:
        if re.fullmatch(pattern, candidate):
            return candidate

    raise TestCaseGeneratorError(
        f"Cannot deterministically generate a string matching pattern '{pattern}' "
        f"with minLength={schema.min_length}, maxLength={schema.max_length}"
    )


def _generate_integer(schema: ApiSchema) -> int:
    """Generate an integer respecting minimum/maximum/exclusive constraints and multipleOf."""
    minimum = schema.minimum
    maximum = schema.maximum

    if minimum is not None:
        value = int(minimum)
        if schema.exclusive_minimum:
            value += 1
    else:
        value = 1

    if maximum is not None:
        max_val = int(maximum)
        if schema.exclusive_maximum:
            max_val -= 1
        value = min(value, max_val)

    # multipleOf: snap to nearest valid multiple
    if schema.multiple_of and schema.multiple_of > 0:
        mult = int(schema.multiple_of)
        if mult > 0:
            # Round up to next multiple if needed
            remainder = value % mult
            if remainder != 0:
                value = value + (mult - remainder)
            # Re-check maximum
            if maximum is not None:
                max_val = int(maximum)
                if schema.exclusive_maximum:
                    max_val -= 1
                value = min(value, max_val)

    return value


def _generate_number(schema: ApiSchema) -> float:
    """Generate a number respecting minimum/maximum/exclusive constraints."""
    minimum = schema.minimum
    maximum = schema.maximum

    if minimum is not None and maximum is not None:
        lo = float(minimum)
        hi = float(maximum)
        if schema.exclusive_minimum and schema.exclusive_maximum:
            if lo >= hi:
                raise TestCaseGeneratorError(
                    f"No valid number: exclusive_minimum={lo} >= exclusive_maximum={hi}"
                )
            return (lo + hi) / 2.0
        if schema.exclusive_minimum:
            if lo >= hi:
                raise TestCaseGeneratorError(
                    f"No valid number: exclusive_minimum={lo} >= maximum={hi}"
                )
            return min(lo + 0.1, hi)
        if schema.exclusive_maximum:
            if lo >= hi:
                raise TestCaseGeneratorError(
                    f"No valid number: minimum={lo} >= exclusive_maximum={hi}"
                )
            return max(lo, hi - 0.1)
        return lo  # both inclusive, use minimum

    if minimum is not None:
        value = float(minimum)
        if schema.exclusive_minimum:
            value += 0.1
        return value

    if maximum is not None:
        max_val = float(maximum)
        if schema.exclusive_maximum:
            max_val -= 0.1
        return max_val

    return 1.0


def _generate_array(schema: ApiSchema) -> list:
    """Generate an array respecting minItems/maxItems/uniqueItems constraints."""
    min_items = schema.min_items if schema.min_items is not None else 1
    max_items = schema.max_items
    item_schema = schema.items or ApiSchema()

    # If maxItems is 0, return empty
    if max_items is not None and max_items == 0:
        return []

    count = min_items
    if max_items is not None:
        count = min(count, max_items)

    if schema.unique_items:
        return _generate_unique_array(item_schema, count)

    item = _generate_value(item_schema)
    return [copy.deepcopy(item) for _ in range(count)]


def _generate_unique_array(item_schema: ApiSchema, count: int) -> list:
    """Generate an array of *count* distinct elements for simple item types.

    Raises ``TestCaseGeneratorError`` for types where deterministic
    uniqueness cannot be guaranteed (object, array, boolean with count > 2).
    """
    item_type = item_schema.type or "string"

    if item_type in ("string",):
        return [_generate_value(item_schema) + f"_{i}" for i in range(count)]
    if item_type in ("integer",):
        base = int(_generate_value(item_schema))
        return [base + i for i in range(count)]
    if item_type in ("number",):
        base = float(_generate_value(item_schema))
        return [base + float(i) for i in range(count)]
    if item_type in ("boolean",):
        if count > 2:
            raise TestCaseGeneratorError(
                "Cannot generate more than 2 unique boolean values"
            )
        return [True, False][:count]

    raise TestCaseGeneratorError(
        f"Cannot deterministically generate uniqueItems array for item type '{item_type}'"
    )


def _generate_object(schema: ApiSchema) -> dict[str, Any]:
    """Generate an object with all defined properties (excluding read_only)."""
    if not schema.properties:
        return {}
    result = {}
    for prop_name, prop_schema in schema.properties.items():
        if prop_schema.read_only:
            continue
        result[prop_name] = _generate_value(prop_schema)
    return result


# ── Mutation functions ───────────────────────────────────────────────────────


def _apply_mutation(
    base: dict[str, Any],
    scenario: TestScenario,
) -> dict[str, Any]:
    """Apply scenario mutation to the base request.  Returns a new dict."""
    data = copy.deepcopy(base)
    cat = scenario.category
    loc = scenario.target_location
    path = scenario.target_path

    if cat == "happy_path":
        return data

    if cat == "required_missing" and loc and path:
        _mutate_delete(data, loc, path)
    elif cat == "null" and loc and path:
        _mutate_set_null(data, loc, path)
    elif cat == "wrong_type" and loc and path:
        _mutate_wrong_type(data, loc, path)

    return data


def _mutate_delete(data: dict, location: str, target_path: str) -> None:
    """Delete the target field."""
    if location in ("query", "header"):
        container = _get_param_container(data, location)
        if container and target_path in container:
            del container[target_path]
    elif location == "cookie":
        cookies = data.get("cookies")
        if cookies and target_path in cookies:
            del cookies[target_path]
    elif location == "body":
        body_path = target_path[5:] if target_path.startswith("body.") else target_path
        _delete_nested(data.get("body"), body_path)


def _mutate_set_null(data: dict, location: str, target_path: str) -> None:
    """Set the target field to None."""
    if location in ("query", "header"):
        container = _get_param_container(data, location)
        if container and target_path in container:
            container[target_path] = "null"
    elif location == "cookie":
        cookies = data.get("cookies")
        if cookies and target_path in cookies:
            cookies[target_path] = "null"
    elif location == "body":
        body_path = target_path[5:] if target_path.startswith("body.") else target_path
        _set_nested(data.get("body"), body_path, None)


def _mutate_wrong_type(data: dict, location: str, target_path: str) -> None:
    """Replace the target field with a type-mismatched value."""
    if location in ("query", "header"):
        container = _get_param_container(data, location)
        if container and target_path in container:
            container[target_path] = "not-a-valid-value"
    elif location == "cookie":
        cookies = data.get("cookies")
        if cookies and target_path in cookies:
            cookies[target_path] = "not-a-valid-value"
    elif location == "path":
        path_params = data.get("path_params")
        if path_params and target_path in path_params:
            path_params[target_path] = "not-a-valid-value"
    elif location == "body":
        body_path = target_path[5:] if target_path.startswith("body.") else target_path
        current = _get_nested(data.get("body"), body_path)
        _set_nested(data.get("body"), body_path, _wrong_type_value(current))


def _get_param_container(data: dict, location: str) -> dict[str, str] | None:
    """Get the appropriate parameter container dict."""
    if location == "query":
        return data.get("query_params")
    elif location == "header":
        return data.get("headers")
    return None


def _wrong_type_value(current: Any) -> Any:
    """Return a value that mismatches the current type."""
    if isinstance(current, int):
        return "not-an-integer"
    elif isinstance(current, float):
        return "not-a-number"
    elif isinstance(current, bool):
        return "not-a-boolean"
    elif isinstance(current, str):
        return 99999
    elif isinstance(current, list):
        return "not-an-array"
    elif isinstance(current, dict):
        return "not-an-object"
    else:
        return "wrong-type"


# ── Nested dict helpers ──────────────────────────────────────────────────────


def _get_nested(obj: Any, dotted_path: str) -> Any:
    """Get a nested value by dotted path (e.g. 'profile.email')."""
    if obj is None:
        return None
    parts = dotted_path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _set_nested(obj: Any, dotted_path: str, value: Any) -> None:
    """Set a nested value by dotted path."""
    if not isinstance(obj, dict):
        return
    parts = dotted_path.split(".")
    current = obj
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _delete_nested(obj: Any, dotted_path: str) -> None:
    """Delete a nested value by dotted path."""
    if not isinstance(obj, dict):
        return
    parts = dotted_path.split(".")
    current = obj
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]


# ── String conversion ────────────────────────────────────────────────────────


def _to_string(value: Any) -> str:
    """Convert a value to string for parameter use."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
