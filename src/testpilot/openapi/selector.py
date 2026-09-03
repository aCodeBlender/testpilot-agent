"""Endpoint Selector — deterministic filtering by tag.

Filters an ``ApiEndpoint`` list by ``include_tags`` / ``exclude_tags``.
Returns a new list; does not mutate the input.
"""

from __future__ import annotations

from testpilot.domain.spec import ApiEndpoint


def select_endpoints(
    endpoints: list[ApiEndpoint],
    *,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
) -> list[ApiEndpoint]:
    """Filter *endpoints* by tag inclusion / exclusion rules.

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

    return result
