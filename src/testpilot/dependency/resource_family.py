"""Resource-family matching for deterministic dependency inference.

A *resource family* groups path segments that refer to the same entity
type across CRUD operations.  Examples:

    /users          -> family "user"
    /users/{userId} -> family "user"
    /orders         -> family "order"
    /orders/{id}    -> family "order"

The canonical slug is derived by:
1. Taking the first non-parameter path segment.
2. Stripping a trailing "s" (simple English plural).

This is intentionally conservative — it only handles obvious plurals.
"""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def resource_family_from_path(path: str) -> str | None:
    """Derive a resource-family slug from a URL path template.

    Returns ``None`` when no usable segment is found (e.g. root path "/").
    """
    for segment in path.strip("/").split("/"):
        if not segment:
            continue
        # Skip parameter placeholders like {id}, {userId}
        if segment.startswith("{") and segment.endswith("}"):
            continue
        slug = segment.lower()
        if not _SLUG_RE.match(slug):
            continue
        # Simple de-pluralise: "users" -> "user", "orders" -> "order",
        # "addresses" -> "address" (strip trailing "es" when stem already
        # ends in "ss").
        # We keep it simple: only strip if the word is > 3 chars.
        if len(slug) > 3:
            if slug.endswith("es") and len(slug) > 4:
                slug = slug[:-2]
            elif slug.endswith("s") and not slug.endswith("ss"):
                slug = slug[:-1]
        return slug
    return None
