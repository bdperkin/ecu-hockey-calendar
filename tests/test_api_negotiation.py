"""Tests for content negotiation, q-value ranking, and dual-format routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.testclient import TestClient

from ecu_hockey_calendar.api import determine_response_format, negotiate_response
from ecu_hockey_calendar.api.app import create_app
from ecu_hockey_calendar.api.negotiation import (
    DEFAULT_TEMPLATES_DIR,
    _build_negotiated_headers,
    _calculate_specificity,
    _compare_media_ranks,
    _is_better_match,
    _is_empty_or_wildcard,
    _matches_target,
    _parse_media_range,
    _parse_q_value,
    _resolve_query_format,
    get_jinja_env,
    highlight_json,
    parse_accept_header,
)


def _make_dummy_request(
    path: str = "/",
    query_string: str = "",
    headers: dict[str, str] | None = None,
) -> Request:
    """Construct a mock Starlette Request for unit testing."""
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query_string.encode("latin-1"),
        "headers": raw_headers,
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# Unit tests for parser and helper functions
# ---------------------------------------------------------------------------


def test_get_jinja_env_caching_and_custom_dir(tmp_path: Path) -> None:
    """Verify get_jinja_env returns shared singleton or custom instance."""
    env1 = get_jinja_env()
    env2 = get_jinja_env()
    assert env1 is env2

    custom_env = get_jinja_env(templates_dir=tmp_path)
    assert custom_env is not env1


def test_parse_q_value() -> None:
    """Verify q-value extraction and clamping."""
    assert _parse_q_value(["charset=utf-8", "q=0.8"]) == 0.8
    assert _parse_q_value(["q=1.5"]) == 1.0
    assert _parse_q_value(["q=-0.5"]) == 0.0
    assert _parse_q_value(["q=invalid"]) == 1.0
    assert _parse_q_value(["charset=utf-8"]) == 1.0


def test_calculate_specificity() -> None:
    """Verify specificity calculations."""
    assert _calculate_specificity("*/*") == 0
    assert _calculate_specificity("text/*") == 1
    assert _calculate_specificity("text/html") == 2
    assert _calculate_specificity("invalid") == -1


def test_parse_media_range() -> None:
    """Verify parsing of individual media ranges."""
    assert _parse_media_range("") is None
    assert _parse_media_range("; ;") is None
    assert _parse_media_range("invalid_no_slash") is None

    parsed = _parse_media_range("text/html; q=0.7; level=1")
    assert parsed == ("text/html", 0.7, 2)


def test_parse_accept_header() -> None:
    """Verify parsing of full Accept headers with whitespace and invalid entries."""
    assert not parse_accept_header(None)
    assert not parse_accept_header("   ")

    parsed = parse_accept_header("text/html, application/json;q=0.9, , invalid")
    assert len(parsed) == 2
    assert parsed[0] == ("text/html", 1.0, 2)
    assert parsed[1] == ("application/json", 0.9, 2)


def test_matches_target() -> None:
    """Verify media type target matching."""
    targets = ("text/html", "application/xhtml+xml")
    assert _matches_target("text/html", targets) is True
    assert _matches_target("*/*", targets) is True
    assert _matches_target("text/*", targets) is True
    assert _matches_target("image/*", targets) is False
    assert _matches_target("application/json", targets) is False


def test_is_better_match() -> None:
    """Verify ranking comparison of quality and specificity."""
    # Higher quality
    assert _is_better_match(0.9, 0, 0.8, 2) is True
    # Same quality, higher specificity
    assert _is_better_match(0.8, 2, 0.8, 1) is True
    # Same quality, same or lower specificity
    assert _is_better_match(0.8, 1, 0.8, 2) is False
    # Lower quality
    assert _is_better_match(0.7, 2, 0.8, 0) is False


def test_resolve_query_format() -> None:
    """Verify query string format resolution."""
    assert _resolve_query_format(None) is None
    assert _resolve_query_format("") is None
    assert _resolve_query_format("html") == "html"
    assert _resolve_query_format("HTML") == "html"
    assert _resolve_query_format("json") == "json"
    assert _resolve_query_format("JSON") == "json"
    assert _resolve_query_format("xml") is None


def test_is_empty_or_wildcard() -> None:
    """Verify detection of absent, empty, or wildcard Accept headers."""
    assert _is_empty_or_wildcard(None) is True
    assert _is_empty_or_wildcard("") is True
    assert _is_empty_or_wildcard("   ") is True
    assert _is_empty_or_wildcard("*/*") is True
    assert _is_empty_or_wildcard("text/html") is False


def test_compare_media_ranks() -> None:
    """Verify ranking logic for HTML vs JSON."""
    # HTML not requested
    assert _compare_media_ranks((0.0, -1), (1.0, 2)) == "json"
    # JSON has higher q
    assert _compare_media_ranks((0.7, 2), (0.9, 2)) == "json"
    # HTML has higher q
    assert _compare_media_ranks((0.9, 2), (0.7, 2)) == "html"
    # Tied q, HTML more specific
    assert _compare_media_ranks((1.0, 2), (1.0, 0)) == "html"
    # Tied q, JSON more specific
    assert _compare_media_ranks((1.0, 0), (1.0, 2)) == "json"
    # Tied q and specificity
    assert _compare_media_ranks((1.0, 2), (1.0, 2)) == "json"


def test_determine_response_format_cases() -> None:
    """Verify all format negotiation signals and overrides."""
    # Query parameter overrides
    req_html_override = _make_dummy_request(
        query_string="format=html",
        headers={"Accept": "application/json"},
    )
    assert determine_response_format(req_html_override) == "html"

    req_json_override = _make_dummy_request(
        query_string="format=json",
        headers={"Accept": "text/html"},
    )
    assert determine_response_format(req_json_override) == "json"

    # Browser default Accept
    req_browser = _make_dummy_request(
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert determine_response_format(req_browser) == "html"

    # curl default
    req_curl = _make_dummy_request(headers={"Accept": "*/*"})
    assert determine_response_format(req_curl) == "json"

    # Header-less
    req_no_header = _make_dummy_request()
    assert determine_response_format(req_no_header) == "json"

    # JSON explicit
    req_json = _make_dummy_request(headers={"Accept": "application/json"})
    assert determine_response_format(req_json) == "json"


def test_highlight_json_tokens() -> None:
    """Verify syntax highlighting produces expected span tags for JSON primitives."""
    payload = {
        "name": "Pirates",
        "active": True,
        "disabled": False,
        "count": 42,
        "negative": -100,
        "exp": 2.5e3,
        "ratio": 3.14,
        "empty": None,
        "sub": {"nested": "value with true and 123 in string"},
        "html_content": "<span>&amp;</span>",
        "items": ["plain string", "string with : colon"],
    }
    html_out = highlight_json(payload)
    assert '<span class="json-key">&quot;name&quot;</span>:' in html_out
    assert '<span class="json-string">&quot;Pirates&quot;</span>' in html_out
    assert '<span class="json-boolean">true</span>' in html_out
    assert '<span class="json-boolean">false</span>' in html_out
    assert '<span class="json-number">42</span>' in html_out
    assert '<span class="json-number">-100</span>' in html_out
    assert '<span class="json-number">2500.0</span>' in html_out
    assert '<span class="json-number">3.14</span>' in html_out
    assert '<span class="json-null">null</span>' in html_out
    assert "value with true and 123 in string" in html_out
    assert "&lt;span&gt;&amp;amp;&lt;/span&gt;" in html_out
    assert '<span class="json-string">&quot;plain string&quot;</span>' in html_out
    assert (
        '<span class="json-string">&quot;string with : colon&quot;</span>' in html_out
    )


def test_build_negotiated_headers() -> None:
    """Verify Vary: Accept header injection."""
    h1 = _build_negotiated_headers(None)
    assert h1 == {"Vary": "Accept"}

    h2 = _build_negotiated_headers({"Vary": "Accept"})
    assert h2 == {"Vary": "Accept"}

    h3 = _build_negotiated_headers({"Vary": "Cookie", "X-Custom": "test"})
    assert h3["Vary"] == "Cookie, Accept"
    assert h3["X-Custom"] == "test"


def test_negotiate_response_unit() -> None:
    """Verify negotiate_response unit execution for both JSON and HTML modes."""
    data = {"status": "ok", "message": "hello"}

    # JSON mode
    req_json = _make_dummy_request(headers={"Accept": "application/json"})
    resp_json = negotiate_response(
        req_json,
        data,
        "root.html",
        status_code=201,
        headers={"X-Test": "1"},
    )
    assert resp_json.status_code == 201
    assert "application/json" in resp_json.headers["Content-Type"]
    assert "Accept" in resp_json.headers["Vary"]
    assert resp_json.headers["X-Test"] == "1"

    # HTML mode with custom context and env
    req_html = _make_dummy_request(query_string="format=html")
    custom_env = get_jinja_env(DEFAULT_TEMPLATES_DIR)
    resp_html = negotiate_response(
        req_html,
        data,
        "root.html",
        context={"custom_key": "custom_val"},
        jinja_env=custom_env,
    )
    assert resp_html.status_code == 200
    assert "text/html" in resp_html.headers["Content-Type"]
    assert "Accept" in resp_html.headers["Vary"]
    assert "East Carolina University" in bytes(resp_html.body).decode("utf-8")

    # HTML mode without context or custom env
    resp_html_default = negotiate_response(
        req_html,
        data,
        "root.html",
    )
    assert resp_html_default.status_code == 200
    assert "text/html" in resp_html_default.headers["Content-Type"]


# ---------------------------------------------------------------------------
# Integration tests on live application GET /
# ---------------------------------------------------------------------------


def test_root_endpoint_content_negotiation_json() -> None:
    """Verify GET / returns identical JSON payload for API and default clients."""
    app = create_app()
    client = TestClient(app)

    # 1. Bare request without Accept header
    r_bare = client.get("/", headers={"Accept": ""})
    assert r_bare.status_code == 200
    assert "application/json" in r_bare.headers["Content-Type"]
    assert "Accept" in r_bare.headers["Vary"]
    data = r_bare.json()
    assert data["status"] == "online"
    assert data["name"] == "ECU Men's Ice Hockey Calendar & Data API"
    assert "/calendar.ics" in data["endpoints"]["calendar_ics"]

    # 2. Accept: */* (curl default, protects deploy gate)
    r_wildcard = client.get("/", headers={"Accept": "*/*"})
    assert r_wildcard.status_code == 200
    assert "application/json" in r_wildcard.headers["Content-Type"]
    assert "Accept" in r_wildcard.headers["Vary"]
    assert r_wildcard.json() == data

    # 3. Explicit Accept: application/json
    r_json = client.get("/", headers={"Accept": "application/json"})
    assert r_json.status_code == 200
    assert "application/json" in r_json.headers["Content-Type"]
    assert r_json.json() == data

    # 4. Explicit override ?format=json
    r_override = client.get(
        "/?format=json",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert r_override.status_code == 200
    assert "application/json" in r_override.headers["Content-Type"]
    assert r_override.json() == data


def test_root_endpoint_content_negotiation_html() -> None:
    """Verify GET / returns styled, responsive HTML for browser clients."""
    app = create_app()
    client = TestClient(app)

    # Browser Accept header
    browser_accept = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8"
    )
    r_html = client.get("/", headers={"Accept": browser_accept})
    assert r_html.status_code == 200
    assert "text/html" in r_html.headers["Content-Type"]
    assert "Accept" in r_html.headers["Vary"]

    html_content = r_html.text
    # Service heading and branding
    assert "ECU Men&#39;s Ice Hockey Calendar &amp; Data API" in html_content
    assert "ONLINE" in html_content
    assert "Official real-time calendar subscription feeds" in html_content

    # Calendar subscription showcase and sync guide link
    assert "Live Calendar Subscription" in html_content
    assert "/calendar.ics" in html_content
    assert "webcal://" in html_content
    assert "docs/calendar_sync.md" in html_content

    # Endpoints directory links
    assert "/schedule" in html_content
    assert "/schedule/embed" in html_content
    assert "/api/schedule.csv" in html_content
    assert "/api/schedule.json" in html_content
    assert "/health" in html_content
    assert "/docs" in html_content

    # "View as JSON" link and embedded pretty-printed JSON payload
    assert "?format=json" in html_content
    assert "View as JSON" in html_content
    assert '<pre class="json-pre">' in html_content
    assert '<span class="json-key">' in html_content
    assert '<span class="json-string">' in html_content

    # Explicit override ?format=html wins over Accept: application/json
    r_override = client.get(
        "/?format=html",
        headers={"Accept": "application/json"},
    )
    assert r_override.status_code == 200
    assert "text/html" in r_override.headers["Content-Type"]
    assert "ONLINE" in r_override.text


def test_root_endpoint_head_requests() -> None:
    """Verify HEAD / returns proper negotiated headers with empty body."""
    app = create_app()
    client = TestClient(app)

    # HEAD JSON
    res_json = client.head("/", headers={"Accept": "application/json"})
    assert res_json.status_code == 200
    assert res_json.text == ""
    assert "application/json" in res_json.headers["Content-Type"]
    assert "Accept" in res_json.headers["Vary"]

    # HEAD HTML
    res_html = client.head(
        "/",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert res_html.status_code == 200
    assert res_html.text == ""
    assert "text/html" in res_html.headers["Content-Type"]
    assert "Accept" in res_html.headers["Vary"]


def test_root_endpoint_openapi_schema() -> None:
    """Verify OpenAPI document accurately reflects JSON and HTML responses on GET /."""
    app = create_app()
    client = TestClient(app)
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()

    root_op = schema["paths"]["/"]["get"]
    assert "General" in root_op["tags"]
    assert root_op["summary"] == "API Service Status and Information"

    content = root_op["responses"]["200"]["content"]
    assert "application/json" in content
    assert "text/html" in content

    json_schema = content["application/json"]["schema"]
    assert json_schema["type"] == "object"
    assert "name" in json_schema["properties"]
    assert "version" in json_schema["properties"]
    assert "status" in json_schema["properties"]
    assert "endpoints" in json_schema["properties"]
