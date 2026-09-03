"""Endpoint Selector — deterministic filtering by tag, ID, and method.

Filters an ``ApiEndpoint`` list by ``include_tags`` / ``exclude_tags``,
``endpoint_ids``, and ``exclude_methods``.
Returns a new list; does not mutate the input.
"""

from __future__ import annotations

from testpilot.domain.spec import ApiEndpoint


def select_endpoints(
    endpoints: list[ApiEndpoint],
    *,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    endpoint_ids: list[str] | None = None,
    exclude_methods: list[str] | None = None,
) -> list[ApiEndpoint]:
    """Filter *endpoints* by tag, ID, and HTTP method.

    Filter order: tags → endpoint IDs → method exclusion.

    Parameters
    ----------
    endpoints:
        Full list of endpoints from ``ApiSpec.endpoints``.
    include_tags:
        If non-empty, only endpoints that have **at least one** tag in
        this list are kept.  Empty list or ``None`` means "keep all".
    exclude_tags:
        Endpoints that have **any** tag in this list are dropped.
        Applied after *include_tags* filtering.
    endpoint_ids:
        If non-empty, only endpoints whose ``id`` is in this list are kept.
        Applied after tag filtering.
    exclude_methods:
        Endpoints whose HTTP method is in this list are dropped.
        Applied last.  Case-insensitive.

    Returns
    -------
    list[ApiEndpoint]
        A new filtered list (order preserved).
    """
    result = list(endpoints)  # shallow copy — do not mutate input

    # ── include filter ──────────────────────────────────────────────────
    if include_tags:
        include_set = set(include_tags)
        result = [ep for ep in result if include_set.intersection(ep.tags)]

    # ── exclude filter ──────────────────────────────────────────────────
    if exclude_tags:
        exclude_set = set(exclude_tags)
        result = [ep for ep in result if not exclude_set.intersection(ep.tags)]

    # ── endpoint ID filter ──────────────────────────────────────────────
    if endpoint_ids:
        id_set = set(endpoint_ids)
        result = [ep for ep in result if ep.id in id_set]

    # ── method exclusion ────────────────────────────────────────────────
    if exclude_methods:
        method_set = {m.upper() for m in exclude_methods}
        result = [ep for ep in result if ep.method.upper() not in method_set]

    return result
