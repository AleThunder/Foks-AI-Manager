from __future__ import annotations

import re
from typing import Any

import requests
from requests import Response

from app.infrastructure.logging import get_logger


class FoksSession:
    """Wrap FOKS HTTP communication, authentication and retry logic."""

    def __init__(self, base_url: str, username: str, password: str, api_prefix: str = "/api/v1") -> None:
        """Create a session client configured for one FOKS environment and account."""
        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/144.0 Safari/537.36"
                )
            }
        )
        self.homepage_csrf: str = ""
        self._is_authenticated = False
        self._auth_logger = get_logger("app.integration.foks.auth")
        self._read_logger = get_logger("app.integration.foks.read")

    def _url(self, path: str) -> str:
        """Convert a relative FOKS path into an absolute URL."""
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    @staticmethod
    def extract_csrf(html: str) -> str:
        """Extract the CSRF token from an HTML page containing the login form."""
        patterns = [
            r'<input[^>]*name="_csrf"[^>]*value="([^"]*)"',
            r'<input[^>]*value="([^"]*)"[^>]*name="_csrf"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        raise RuntimeError("CSRF token not found on homepage")

    def _is_login_page(self, response: Response) -> bool:
        """Detect whether the server responded with a login page instead of the requested resource."""
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            return False

        url = (response.url or "").lower()
        body = response.text.lower()
        return "/login" in url or ('name="_csrf"' in body and "/login" in body)

    def _is_auth_failure_response(self, response: Response) -> bool:
        """Recognize redirects or responses that mean the current session is no longer authenticated."""
        if response.status_code in (401, 403):
            return True

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "").lower()
            if "/login" in location:
                return True

        return self._is_login_page(response)

    def _request(
        self,
        method: str,
        path: str,
        *,
        require_auth: bool = True,
        allow_retry: bool = True,
        **kwargs: Any,
    ) -> Response:
        """Send one HTTP request and transparently retry once after re-authentication when needed."""
        if require_auth:
            self.ensure_authenticated()

        response = self.session.request(method, self._url(path), **kwargs)

        if require_auth and allow_retry and self._is_auth_failure_response(response):
            self._auth_logger.warning(
                "auth_retry_required",
                extra={"event": "auth_retry_required", "path": path, "method": method},
            )
            self._is_authenticated = False
            self.login(force=True)
            return self._request(
                method,
                path,
                require_auth=require_auth,
                allow_retry=False,
                **kwargs,
            )

        response.raise_for_status()
        return response

    def ensure_authenticated(self) -> None:
        """Log in lazily before the first protected request."""
        if self._is_authenticated:
            return
        self.login()

    def login(self, force: bool = False) -> None:
        """Perform the FOKS login flow and refresh cookies/csrf state."""
        if self._is_authenticated and not force:
            return

        if force:
            self._auth_logger.info("auth_relogin_started", extra={"event": "auth_relogin_started"})
            self.session.cookies.clear()
            self._is_authenticated = False
        else:
            self._auth_logger.info("auth_login_started", extra={"event": "auth_login_started"})

        homepage_response = self._request(
            "GET",
            "/",
            require_auth=False,
            headers={"Accept": "text/html,*/*"},
            timeout=30,
        )
        self.homepage_csrf = self.extract_csrf(homepage_response.text)

        response = self._request(
            "POST",
            "/login",
            require_auth=False,
            params={
                "username": self.username,
                "password": self.password,
                "remember-me": "on",
                "_csrf": self.homepage_csrf,
            },
            headers={"Accept": "text/html,*/*"},
            allow_redirects=False,
            timeout=30,
        )

        if response.status_code not in (200, 302):
            self._auth_logger.error(
                "auth_login_failed_status",
                extra={"event": "auth_login_failed_status", "status_code": response.status_code},
            )
            raise RuntimeError(f"Login failed: {response.status_code} {response.text[:300]}")

        if self._is_auth_failure_response(response):
            self._auth_logger.error("auth_login_failed", extra={"event": "auth_login_failed"})
            raise RuntimeError("Login failed: FOKS returned login page after authentication attempt")

        self._is_authenticated = True
        self._auth_logger.info("auth_login_completed", extra={"event": "auth_login_completed"})

    def get_html(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Fetch one HTML page from FOKS and return the response body."""
        self._read_logger.info(
            "foks_html_request",
            extra={"event": "foks_html_request", "path": path, "params": params or {}},
        )
        response = self._request(
            "GET",
            path,
            params=params,
            headers={"Accept": "text/html,*/*"},
            timeout=30,
        )
        return response.text

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Fetch one JSON endpoint from FOKS and deserialize the response body."""
        self._read_logger.info(
            "foks_json_request",
            extra={"event": "foks_json_request", "path": path, "params": params or {}},
        )
        response = self._request(
            "GET",
            path,
            params=params,
            headers={"Accept": "application/json"},
            timeout=30,
        )
        return response.json()

    def build_json_headers(self, csrf_token: str, referer_path: str = "/c/products") -> dict[str, str]:
        """Build the header set required for JSON requests back to the FOKS UI endpoints."""
        return {
            "Accept": "*/*",
            "Content-Type": "application/json; charset=UTF-8",
            "Origin": self.base_url,
            "Referer": self._url(referer_path),
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

    def post_json(self, path: str, json_body: dict[str, Any], csrf_token: str) -> Any:
        """Send a JSON POST request to FOKS and normalize the response shape."""
        response = self._request(
            "POST",
            path,
            json=json_body,
            headers=self.build_json_headers(csrf_token=csrf_token),
            timeout=60,
        )
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text
