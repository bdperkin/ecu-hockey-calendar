"""Tests for content-negotiated error responses and handlers."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi import HTTPException as FastApiHTTPException
from fastapi.exceptions import StarletteHTTPException
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.errors import (
    _format_input_value,
    _format_location,
    _resolve_error_message,
    _resolve_error_title,
    format_validation_error,
    register_exception_handlers,
)


def test_format_location_variants() -> None:
    """Verify _format_location handles tuples, lists, strings, and empty cases."""
    assert _format_location(("query", "limit")) == "query -> limit"
    assert _format_location(["body", "user", "name"]) == "body -> user -> name"
    assert _format_location("simple_field") == "simple_field"
    assert _format_location(()) == "(unknown)"
    assert _format_location(None) == "(unknown)"


def test_format_input_value_variants() -> None:
    """Verify _format_input_value handles None, strings, and long values."""
    assert _format_input_value(None) == "None"
    assert _format_input_value("short") == "short"

    long_str = "a" * 80
    formatted_str = _format_input_value(long_str)
    assert formatted_str.endswith("...")
    assert len(formatted_str) == 60

    assert _format_input_value(12345) == "12345"

    long_dict = {"key_" + str(i): "val_" + str(i) for i in range(10)}
    formatted_dict = _format_input_value(long_dict)
    assert formatted_dict.endswith("...")


def test_format_validation_error() -> None:
    """Verify format_validation_error returns structured dictionary."""
    raw_err = {
        "loc": ("query", "home_only"),
        "msg": "Input should be a valid boolean",
        "type": "bool_parsing",
        "input": "maybe",
    }
    formatted = format_validation_error(raw_err)
    assert formatted == {
        "field": "query -> home_only",
        "message": "Input should be a valid boolean",
        "type": "bool_parsing",
        "input": "maybe",
    }

    # Test empty / default fallback
    empty_formatted = format_validation_error({})
    assert empty_formatted["field"] == "(unknown)"
    assert empty_formatted["message"] == "Validation error"
    assert empty_formatted["type"] == "value_error"
    assert empty_formatted["input"] == "None"


def test_resolve_error_title_and_message() -> None:
    """Verify title and message resolution for known and unknown status codes."""
    assert _resolve_error_title(404) == "404 - Page Not Found"
    assert _resolve_error_title(401) == "401 - Authentication Required"
    assert _resolve_error_title(422) == "422 - Validation Error"
    assert _resolve_error_title(500) == "500 - Internal Server Error"
    assert _resolve_error_title(418) == "418 - HTTP Error"

    assert "not be found" in _resolve_error_message(404)
    assert "Administrative credentials" in _resolve_error_message(401)
    assert "schema validation" in _resolve_error_message(422)
    assert "unexpected error" in _resolve_error_message(500)
    assert "HTTP error occurred" in _resolve_error_message(418)


def test_http_exception_early_return_when_body_not_allowed() -> None:
    """Verify HTTP status codes disallowing bodies return bodyless response."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/not-modified")
    def trigger_304() -> None:
        """Trigger 304 Not Modified HTTP exception."""
        raise StarletteHTTPException(status_code=304, headers={"ETag": '"abc"'})

    client = TestClient(test_app)
    resp = client.get("/not-modified")
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers.get("etag") == '"abc"'


def test_http_404_negotiation_browser_vs_api() -> None:
    """Verify 404 returns styled HTML for browsers and clean JSON for API clients."""
    app = create_app()
    client = TestClient(app)

    # 1. Browser Accept header -> HTML
    html_resp = client.get(
        "/nonexistent-page",
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
    )
    assert html_resp.status_code == 404
    assert "text/html" in html_resp.headers["content-type"]
    assert "Vary" in html_resp.headers
    assert "Accept" in html_resp.headers["Vary"]
    assert "HTTP 404" in html_resp.text
    assert "404 - Page Not Found" in html_resp.text
    assert "Full Schedule" in html_resp.text
    assert "View as JSON" in html_resp.text

    # 2. curl / default */* Accept header -> JSON
    json_resp = client.get("/nonexistent-page", headers={"Accept": "*/*"})
    assert json_resp.status_code == 404
    assert "application/json" in json_resp.headers["content-type"]
    assert json_resp.json() == {"detail": "Not Found"}
    assert "Vary" in json_resp.headers
    assert "Accept" in json_resp.headers["Vary"]

    # 3. Absent Accept header -> JSON
    bare_client = TestClient(app)
    bare_resp = bare_client.get("/nonexistent-page")
    assert bare_resp.status_code == 404
    assert "application/json" in bare_resp.headers["content-type"]
    assert bare_resp.json() == {"detail": "Not Found"}


def test_http_404_format_query_parameter_override() -> None:
    """Verify ?format= query parameter overrides Accept headers on 404."""
    app = create_app()
    client = TestClient(app)

    # Force JSON via ?format=json even with browser Accept
    forced_json = client.get(
        "/nonexistent-page?format=json",
        headers={"Accept": "text/html"},
    )
    assert forced_json.status_code == 404
    assert "application/json" in forced_json.headers["content-type"]
    assert forced_json.json() == {"detail": "Not Found"}

    # Force HTML via ?format=html even with curl Accept
    forced_html = client.get(
        "/nonexistent-page?format=html",
        headers={"Accept": "*/*"},
    )
    assert forced_html.status_code == 404
    assert "text/html" in forced_html.headers["content-type"]
    assert "HTTP 404" in forced_html.text


def test_http_401_unauthorized_preserves_www_authenticate() -> None:
    """Verify 401 preserves WWW-Authenticate header in both HTML and JSON."""
    app = create_app()
    client = TestClient(app)

    # 1. HTML request
    html_resp = client.get("/api/v1/conflicts", headers={"Accept": "text/html"})
    assert html_resp.status_code == 401
    assert "text/html" in html_resp.headers["content-type"]
    assert html_resp.headers.get("www-authenticate") == "Bearer"
    assert "Vary" in html_resp.headers
    assert "Accept" in html_resp.headers["Vary"]
    assert "Administrative Authentication Required" in html_resp.text
    assert "Authorization: Bearer" in html_resp.text
    assert "X-API-Key" in html_resp.text

    # 2. JSON request
    json_resp = client.get("/api/v1/conflicts", headers={"Accept": "application/json"})
    assert json_resp.status_code == 401
    assert "application/json" in json_resp.headers["content-type"]
    assert json_resp.headers.get("www-authenticate") == "Bearer"
    assert "Vary" in json_resp.headers
    assert "Accept" in json_resp.headers["Vary"]
    assert "detail" in json_resp.json()


def test_http_405_method_not_allowed() -> None:
    """Verify 405 Method Not Allowed is properly negotiated in HTML and JSON."""
    app = create_app()
    client = TestClient(app)

    # POST to a GET-only endpoint
    html_resp = client.post("/health", headers={"Accept": "text/html"})
    assert html_resp.status_code == 405
    assert "text/html" in html_resp.headers["content-type"]
    assert "HTTP 405" in html_resp.text
    assert "405 - Method Not Allowed" in html_resp.text

    json_resp = client.post("/health", headers={"Accept": "application/json"})
    assert json_resp.status_code == 405
    assert "application/json" in json_resp.headers["content-type"]
    assert json_resp.json() == {"detail": "Method Not Allowed"}


def test_validation_error_422_negotiation() -> None:
    """Verify 422 validation errors render table in HTML and Pydantic list in JSON."""
    app = create_app()
    client = TestClient(app)

    url = "/api/schedule.json?home_only=maybe"

    # 1. HTML request
    html_resp = client.get(url, headers={"Accept": "text/html"})
    assert html_resp.status_code == 422
    assert "text/html" in html_resp.headers["content-type"]
    assert "HTTP 422" in html_resp.text
    assert "Validation Errors (1)" in html_resp.text
    assert "query -&gt; home_only" in html_resp.text or "home_only" in html_resp.text
    assert "bool_parsing" in html_resp.text
    assert "maybe" in html_resp.text
    assert "Vary" in html_resp.headers
    assert "Accept" in html_resp.headers["Vary"]

    # 2. JSON request
    json_resp = client.get(url, headers={"Accept": "application/json"})
    assert json_resp.status_code == 422
    assert "application/json" in json_resp.headers["content-type"]
    detail = json_resp.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["type"] == "bool_parsing"
    assert detail[0]["loc"] == ["query", "home_only"]


def test_unhandled_500_exception_logging_and_sanitization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify 500 handler logs server-side and leaks no traceback to clients."""
    test_app = create_app()

    @test_app.get("/trigger-crash")
    def trigger_crash() -> None:
        """Trigger an intentional unhandled exception for testing."""
        raise RuntimeError("Confidential database password leak")

    client = TestClient(test_app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR):
        # 1. HTML request
        html_resp = client.get("/trigger-crash", headers={"Accept": "text/html"})
        assert html_resp.status_code == 500
        assert "text/html" in html_resp.headers["content-type"]
        assert "HTTP 500" in html_resp.text
        assert "500 - Internal Server Error" in html_resp.text
        # Security assertion: secret must NOT leak to client
        assert "Confidential database password leak" not in html_resp.text
        assert "RuntimeError" not in html_resp.text
        assert "Traceback" not in html_resp.text

        # 2. JSON request
        json_resp = client.get("/trigger-crash", headers={"Accept": "*/*"})
        assert json_resp.status_code == 500
        assert "application/json" in json_resp.headers["content-type"]
        assert json_resp.json() == {"detail": "Internal Server Error"}
        assert "Confidential database password leak" not in json_resp.text

    # Verify server-side logging captured the traceback
    assert "Unhandled server exception" in caplog.text
    assert "Confidential database password leak" in caplog.text


def test_head_request_handling_on_errors() -> None:
    """Verify HEAD requests on error status codes return empty bodies with headers."""
    app = create_app()
    client = TestClient(app)

    # 1. HEAD on 404 (HTML accept)
    head_html = client.head("/nonexistent-page", headers={"Accept": "text/html"})
    assert head_html.status_code == 404
    assert "text/html" in head_html.headers["content-type"]
    assert head_html.content == b""

    # 2. HEAD on 404 (JSON accept)
    head_json = client.head("/nonexistent-page", headers={"Accept": "application/json"})
    assert head_json.status_code == 404
    assert "application/json" in head_json.headers["content-type"]
    assert head_json.content == b""

    # 3. HEAD on 405 (Method Not Allowed on GET-only endpoint)
    head_405 = client.head("/api/v1/conflicts", headers={"Accept": "application/json"})
    assert head_405.status_code == 405
    assert head_405.content == b""

    # 4. HEAD on 401 with an authenticated route allowing HEAD
    auth_app = FastAPI()
    register_exception_handlers(auth_app)

    @auth_app.api_route("/auth-head", methods=["GET", "HEAD"])
    def auth_head() -> None:
        """Endpoint requiring authentication that allows HEAD requests."""
        raise StarletteHTTPException(
            status_code=401,
            detail="Auth required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_client = TestClient(auth_app)
    head_401 = auth_client.head("/auth-head", headers={"Accept": "application/json"})
    assert head_401.status_code == 401
    assert head_401.headers.get("www-authenticate") == "Bearer"
    assert head_401.content == b""


def test_conditional_304_responses_unaffected_by_error_handlers() -> None:
    """Verify conditional 304 responses on calendar feeds are preserved."""
    app = create_app()
    client = TestClient(app)

    # Get initial feed to extract ETag
    init_resp = client.get("/calendar.ics")
    assert init_resp.status_code == 200
    etag = init_resp.headers.get("etag")
    assert etag is not None

    # Conditional request with If-None-Match
    cond_resp = client.get("/calendar.ics", headers={"If-None-Match": etag})
    assert cond_resp.status_code == 304
    assert cond_resp.content == b""


def test_fastapi_http_exception_inheritance() -> None:
    """Verify FastApiHTTPException is handled by http_exception_handler."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/raise-fastapi-http")
    def raise_fastapi_http() -> None:
        """Raise a FastAPI HTTPException."""
        raise FastApiHTTPException(
            status_code=403,
            detail="Forbidden custom message",
        )

    client = TestClient(test_app)
    html_resp = client.get("/raise-fastapi-http", headers={"Accept": "text/html"})
    assert html_resp.status_code == 403
    assert "HTTP 403" in html_resp.text
    assert "Forbidden custom message" in html_resp.text

    json_resp = client.get(
        "/raise-fastapi-http",
        headers={"Accept": "application/json"},
    )
    assert json_resp.status_code == 403
    assert json_resp.json() == {"detail": "Forbidden custom message"}
