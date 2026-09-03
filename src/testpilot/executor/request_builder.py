"""RequestBuilder — T0203.

Constructs request data suitable for httpx from a TestCase + AppConfig.

Does NOT send HTTP — only prepares the request dict.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from testpilot.domain.testing import TestCase
from testpilot.executor.exceptions import RequestBuildError


class RequestBuilder:
    """Builds request data from a ``TestCase``.

    Parameters
    ----------
    base_url:
        Target base URL (e.g. ``http://localhost:8080``).
    bearer_token:
        Optional bearer token for ``Authorization`` header.
    custom_headers:
        Optional static headers to include in every request.
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str | None = None,
        custom_headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._custom_headers = custom_headers or {}

    def build(
        self,
        case: TestCase,
        *,
        is_missing_auth: bool = False,
    ) -> dict[str, Any]:
        """Build request data from *case*.

        Parameters
        ----------
        case:
            The test case to build a request for.
        is_missing_auth:
            If ``True``, strip **all** Authorization headers (case-insensitive)
            from every source (custom_headers, case.headers, bearer token).

        Returns
        -------
        dict
            Keys: ``method``, ``url``, ``headers``, ``params``, ``cookies``, ``body``.

        Raises
        ------
        RequestBuildError
            If a path template parameter has no corresponding value.
        """
        url = self._build_url(case)
        headers = self._build_headers(case, is_missing_auth=is_missing_auth)

        return {
            "method": case.method,
            "url": url,
            "headers": headers,
            "params": dict(case.query_params),
            "cookies": dict(case.cookies),
            "body": case.body,
        }

    def _build_url(self, case: TestCase) -> str:
        """Construct the final URL with path parameter substitution.

        Path parameter values are URL-encoded (``urllib.parse.quote(safe="")``)
        so that special characters like ``/`` or spaces do not break the path.
        """
        path = case.path

        def _replace(match: re.Match) -> str:
            param_name = match.group(1)
            if param_name not in case.path_params:
                raise RequestBuildError(
                    f"Path parameter '{{{param_name}}}' has no value in path_params"
                )
            return quote(case.path_params[param_name], safe="")

        resolved_path = re.sub(r"\{([^}]+)\}", _replace, path)

        # Join base_url + path without double slashes
        url = f"{self._base_url}/{resolved_path.lstrip('/')}"
        return url

    def _build_headers(
        self,
        case: TestCase,
        *,
        is_missing_auth: bool,
    ) -> dict[str, str]:
        """Merge headers: custom → case → bearer token.

        When ``is_missing_auth`` is True, all Authorization headers
        (case-insensitive) are stripped from every layer.
        """
        headers: dict[str, str] = {}

        # 1. Custom headers (base layer)
        headers.update(self._custom_headers)

        # 2. Case headers (override custom)
        headers.update(case.headers)

        # 3. Bearer token (unless missing_auth)
        if self._bearer_token and not is_missing_auth:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        # 4. Strip Authorization if missing_auth (case-insensitive)
        if is_missing_auth:
            keys_to_remove = [k for k in headers if k.lower() == "authorization"]
            for k in keys_to_remove:
                del headers[k]

        return headers
