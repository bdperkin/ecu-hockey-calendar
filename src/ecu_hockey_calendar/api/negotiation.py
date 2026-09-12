"""HTTP content negotiation utilities for dual-format (HTML / JSON) endpoints."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import jinja2
from fastapi.responses import HTMLResponse, JSONResponse

from ecu_hockey_calendar.version import __version__

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import Request, Response

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
MIME_HTML = "text/html"
MIME_XHTML = "application/xhtml+xml"
MIME_JSON = "application/json"
MIME_ALL = "*/*"

_JSON_TOKEN_REGEX = re.compile(
    r'(?P<string>"(?:[^"\\]|\\.)*")(?P<colon>\s*:)?|'
    r"(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|"
    r"(?P<boolean>true|false)|"
    r"(?P<null>null)",
)

_ENV_CACHE: dict[str, jinja2.Environment] = {}


def get_jinja_env(templates_dir: Path | str | None = None) -> jinja2.Environment:
    """Return or create a shared Jinja2 environment.

    Args:
        templates_dir: Optional directory override.

    Returns:
        Jinja2 Environment instance.
    """
    target_dir = (
        str(templates_dir) if templates_dir is not None else str(DEFAULT_TEMPLATES_DIR)
    )
    if target_dir not in _ENV_CACHE:
        _ENV_CACHE[target_dir] = jinja2.Environment(
            loader=jinja2.FileSystemLoader(target_dir),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
        )

    return _ENV_CACHE[target_dir]


def _replace_json_token(match: re.Match[str]) -> str:
    """Format matching regex token into an HTML span tag."""
    string_val = match.group("string")
    if string_val is not None:
        val = html.escape(string_val)
        colon = html.escape(match.group("colon") or "")
        if colon:
            return f'<span class="json-key">{val}</span>{colon}'

        return f'<span class="json-string">{val}</span>'

    kind = match.lastgroup
    val = html.escape(match.group(0))
    return f'<span class="json-{kind}">{val}</span>'


def highlight_json(data: object) -> str:
    """Format and syntax-highlight JSON data with HTML spans.

    Args:
        data: Data payload to format and highlight.

    Returns:
        HTML snippet containing color-coded syntax spans.
    """
    formatted = json.dumps(data, indent=2)
    return _JSON_TOKEN_REGEX.sub(_replace_json_token, formatted)


def _parse_q_value(params: list[str]) -> float:
    """Extract q-factor weight from media range parameters."""
    for param in params:
        if param.startswith("q="):
            try:
                return max(0.0, min(1.0, float(param[2:].strip())))
            except ValueError:
                return 1.0

    return 1.0


def _calculate_specificity(media_type: str) -> int:
    """Calculate MIME specificity rank (2 for type/sub, 1 for type/*, 0 for */*)."""
    if media_type == MIME_ALL:
        return 0

    if media_type.endswith("/*"):
        return 1

    return 2 if "/" in media_type else -1


def _parse_media_range(item: str) -> tuple[str, float, int] | None:
    """Parse a single media range item from an Accept header."""
    parts = [p.strip() for p in item.split(";") if p.strip()]
    if not parts:
        return None

    media_type = parts[0].lower()
    specificity = _calculate_specificity(media_type)
    if specificity < 0:
        return None

    q_val = _parse_q_value(parts[1:])
    return media_type, q_val, specificity


def parse_accept_header(accept_header: str | None) -> list[tuple[str, float, int]]:
    """Parse an HTTP Accept header into a list of media ranges with q-values.

    Args:
        accept_header: Raw Accept header value.

    Returns:
        List of (media_type, q_value, specificity) tuples.
    """
    if not accept_header or not accept_header.strip():
        return []

    ranges: list[tuple[str, float, int]] = []
    for raw_item in accept_header.split(","):
        parsed = _parse_media_range(raw_item)
        if parsed is not None:
            ranges.append(parsed)

    return ranges


def _matches_target(media_type: str, target_types: tuple[str, ...]) -> bool:
    """Check whether media type matches target types or wildcards."""
    if media_type in target_types or media_type == MIME_ALL:
        return True

    return media_type == "text/*" and any(t.startswith("text/") for t in target_types)


def _is_better_match(
    q_val: float,
    spec: int,
    best_q: float,
    best_spec: int,
) -> bool:
    """Check whether (q_val, spec) ranks strictly higher than current best."""
    if q_val > best_q:
        return True

    return q_val == best_q and spec > best_spec


def _find_best_match(
    target_types: tuple[str, ...],
    parsed_ranges: list[tuple[str, float, int]],
) -> tuple[float, int]:
    """Find the highest quality and specificity for target media types."""
    best_q = 0.0
    best_spec = -1
    for media_type, q_val, spec in parsed_ranges:
        if _matches_target(media_type, target_types) and _is_better_match(
            q_val,
            spec,
            best_q,
            best_spec,
        ):
            best_q, best_spec = q_val, spec

    return best_q, best_spec


def _resolve_query_format(query_format: str | None) -> str | None:
    """Extract valid format override from query string."""
    if not query_format:
        return None

    fmt = query_format.strip().lower()
    if fmt in ("html", "json"):
        return fmt

    return None


def _is_empty_or_wildcard(header: str | None) -> bool:
    """Check whether accept header is missing, empty, or bare wildcard."""
    if not header:
        return True

    cleaned = header.strip()
    return not cleaned or cleaned == MIME_ALL


def _compare_media_ranks(
    html_rank: tuple[float, int],
    json_rank: tuple[float, int],
) -> str:
    """Compare (q_value, specificity) ranks for HTML and JSON."""
    q_html, spec_html = html_rank
    q_json, spec_json = json_rank
    if q_html <= 0.0 or q_html < q_json:
        return "json"

    if q_html > q_json:
        return "html"

    return "html" if spec_html > spec_json else "json"


def _negotiate_accept_header(accept_header: str | None) -> str:
    """Rank HTML vs JSON preferences from Accept header."""
    if _is_empty_or_wildcard(accept_header):
        return "json"

    parsed = parse_accept_header(accept_header)
    html_rank = _find_best_match((MIME_HTML, MIME_XHTML), parsed)
    json_rank = _find_best_match((MIME_JSON,), parsed)
    return _compare_media_ranks(html_rank, json_rank)


def determine_response_format(request: Request) -> str:
    """Determine response format ('html' or 'json') from request signals.

    Args:
        request: FastAPI / Starlette request.

    Returns:
        'html' if HTML was negotiated, else 'json'.
    """
    override = _resolve_query_format(request.query_params.get("format"))
    if override is not None:
        return override

    return _negotiate_accept_header(request.headers.get("accept"))


def _build_negotiated_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Ensure Vary: Accept is included in response headers."""
    resp_headers = dict(headers) if headers else {}
    existing_vary = resp_headers.get("Vary")
    if not existing_vary:
        resp_headers["Vary"] = "Accept"
    elif "Accept" not in [v.strip() for v in existing_vary.split(",")]:
        resp_headers["Vary"] = f"{existing_vary}, Accept"

    return resp_headers


def negotiate_response(
    request: Request,
    data: Mapping[str, object],
    template_name: str,
    *,
    context: Mapping[str, object] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    jinja_env: jinja2.Environment | None = None,
) -> Response:
    """Select and render HTML or JSON response based on content negotiation.

    Args:
        request: Incoming FastAPI / Starlette request.
        data: Domain payload dictionary.
        template_name: Jinja2 template file to render for HTML views.
        context: Optional additional context parameters for Jinja2 rendering.
        status_code: HTTP response status code (default 200).
        headers: Optional extra response headers.
        jinja_env: Optional custom Jinja2 Environment.

    Returns:
        Starlette HTMLResponse or JSONResponse.
    """
    resp_headers = _build_negotiated_headers(headers)
    fmt = determine_response_format(request)

    if fmt == "json":
        return JSONResponse(
            content=data,
            status_code=status_code,
            headers=resp_headers,
        )

    json_url = str(request.url.include_query_params(format="json"))
    render_context: dict[str, object] = {
        "request": request,
        "data": data,
        "json_payload": highlight_json(data),
        "json_url": json_url,
        "service_version": __version__,
    }
    if context:
        render_context.update(context)

    env = jinja_env or get_jinja_env()
    template = env.get_template(template_name)
    rendered = template.render(render_context)
    return HTMLResponse(
        content=rendered,
        status_code=status_code,
        headers=resp_headers,
    )
