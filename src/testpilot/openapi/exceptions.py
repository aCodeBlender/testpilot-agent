"""Lightweight exception types for OpenAPI loading and mapping."""


class LoaderError(Exception):
    """Raised when an OpenAPI spec cannot be loaded or parsed."""


class MapperError(Exception):
    """Raised when a resolved OpenAPI dict cannot be mapped to domain models."""
