from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.infrastructure.foks.session import FoksSession


def make_response(
    *,
    status_code: int = 200,
    text: str = "",
    headers: dict[str, str] | None = None,
    url: str = "https://my.foks.biz/c/products",
) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {"Content-Type": "text/html; charset=UTF-8"}
    response.url = url
    response.raise_for_status = Mock()
    response.json = Mock(return_value={})
    return response


class FoksSessionTests(unittest.TestCase):
    def test_get_html_logs_in_before_first_protected_request(self) -> None:
        mock_http = Mock()
        mock_http.request.side_effect = [
            make_response(
                text='<html><input name="_csrf" value="homepage-token"></html>',
                url="https://my.foks.biz/",
            ),
            make_response(
                status_code=302,
                headers={"Location": "/c/products"},
                url="https://my.foks.biz/login",
            ),
            make_response(text="<html>ok</html>"),
        ]
        mock_http.cookies = Mock()

        with patch("app.infrastructure.foks.session.requests.Session", return_value=mock_http):
            session = FoksSession("https://my.foks.biz", "user", "pass")
            html = session.get_html("/c/products")

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(mock_http.request.call_count, 3)

    def test_get_json_reauths_and_retries_when_session_expires(self) -> None:
        mock_http = Mock()
        login_page = "<html><form action='/login'><input name=\"_csrf\" value=\"token\"></form></html>"
        final_json_response = make_response(
            headers={"Content-Type": "application/json"},
            text='{"ok": true}',
            url="https://my.foks.biz/api/v1/test",
        )
        final_json_response.json.return_value = {"ok": True}
        mock_http.request.side_effect = [
            make_response(
                text='<html><input name="_csrf" value="homepage-token-1"></html>',
                url="https://my.foks.biz/",
            ),
            make_response(
                status_code=302,
                headers={"Location": "/c/products"},
                url="https://my.foks.biz/login",
            ),
            make_response(text=login_page, url="https://my.foks.biz/login"),
            make_response(
                text='<html><input name="_csrf" value="homepage-token-2"></html>',
                url="https://my.foks.biz/",
            ),
            make_response(
                status_code=302,
                headers={"Location": "/c/products"},
                url="https://my.foks.biz/login",
            ),
            final_json_response,
        ]
        mock_http.cookies = Mock()

        with patch("app.infrastructure.foks.session.requests.Session", return_value=mock_http):
            session = FoksSession("https://my.foks.biz", "user", "pass")
            payload = session.get_json("/api/v1/test")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(mock_http.request.call_count, 6)
        mock_http.cookies.clear.assert_called_once()

    def test_build_json_headers_includes_csrf_and_referer(self) -> None:
        with patch("app.infrastructure.foks.session.requests.Session", return_value=Mock()):
            session = FoksSession("https://my.foks.biz", "user", "pass")

        headers = session.build_json_headers("csrf-token", referer_path="/c/products/productModal")

        self.assertEqual(headers["X-CSRF-TOKEN"], "csrf-token")
        self.assertEqual(headers["Referer"], "https://my.foks.biz/c/products/productModal")
        self.assertEqual(headers["Origin"], "https://my.foks.biz")


if __name__ == "__main__":
    unittest.main()
