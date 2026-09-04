"""Run-scoped runtime state for Phase 3D.

RuntimeState captures scalar values extracted from responses *during* a
test run.  It is:

- **Run-scoped**: one instance per Runner invocation.
- **Ephemeral**: never persisted to disk.
- **Secret-safe**: secret values are NEVER stored — ``put()`` raises
  ``ExtractionError`` when ``scalar.secret=True``.
- **No cross-run memory**: each run starts with a fresh state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from testpilot.dependency.exceptions import ExtractionError
from testpilot.dependency.models import ExtractedScalar


@dataclass(frozen=True)
class RuntimeValue:
    """One captured scalar with provenance and secret flag."""

    value: Any
    source_endpoint_id: str
    pointer: str
    secret: bool = False


class RuntimeState:
    """Run-scoped key-value store for extracted response scalars.

    Keys are ``(endpoint_id, pointer)`` tuples.  Values are RuntimeValue
    instances.  Only the *last* value per key is retained (no history).

    Secret values are **never** stored — ``put()`` raises ``ExtractionError``
    when ``scalar.secret=True``.

    Usage::

        state = RuntimeState()
        state.put("getUserById", "/id", ExtractedScalar(...))
        val = state.get("getUserById", "/id")
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], RuntimeValue] = {}

    def put(self, endpoint_id: str, pointer: str, scalar: ExtractedScalar) -> None:
        """Store a scalar extracted from *endpoint_id*'s response.

        Raises ExtractionError when ``scalar.secret=True`` — secret values
        must never enter ordinary RuntimeState.
        """
        if scalar.secret:
            raise ExtractionError(
                f"Refusing to store secret value from {endpoint_id!r} "
                f"at pointer {pointer!r} in RuntimeState"
            )
        self._store[(endpoint_id, pointer)] = RuntimeValue(
            value=scalar.value,
            source_endpoint_id=endpoint_id,
            pointer=pointer,
            secret=False,
        )

    def get(self, endpoint_id: str, pointer: str) -> RuntimeValue | None:
        """Retrieve a previously stored value, or ``None``."""
        return self._store.get((endpoint_id, pointer))

    def get_value(self, endpoint_id: str, pointer: str) -> Any | None:
        """Convenience: return just the raw value, or ``None``."""
        rv = self.get(endpoint_id, pointer)
        return rv.value if rv is not None else None

    def resolve(self, endpoint_id: str, pointer: str) -> Any:
        """Like get_value but raises KeyError when missing."""
        rv = self.get(endpoint_id, pointer)
        if rv is None:
            raise KeyError(f"No runtime value for ({endpoint_id!r}, {pointer!r})")
        return rv.value

    def has(self, endpoint_id: str, pointer: str) -> bool:
        """Check whether a value is stored."""
        return (endpoint_id, pointer) in self._store

    def clear(self) -> None:
        """Remove all stored values."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return f"RuntimeState({len(self)} values)"
