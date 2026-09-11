"""Content-negotiated exception handlers for HTTP, validation, and server errors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, StarletteHTTPException
from fastapi.responses import Response
from fastapi.utils import is_body_allowed_for_status_code

from ecu_hockey_calendar.api.negotiation import negotiate_response

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

_HTTP_STATUS_TITLES: dict[int, str] = {
    400: "400 - Bad Request",
    401: "401 - Authentication Required",
    403: "403 - Forbidden",
    404: "404 - Page Not Found",
    405: "405 - Method Not Allowed",
    409: "409 - Resource Conflict",
    422: "422 - Validation Error",
    429: "429 - Too Many Requests",
    500: "500 - Internal Server Error",
    501: "501 - Not Implemented",
    502: "502 - Bad Gateway",
    503: "503 - Service Unavailable",
}

_HTTP_STATUS_MESSAGES: dict[int, str] = {
    400: (
        "The server could not understand the request due to invalid syntax or"
        " parameters."
    ),
    401: "Administrative credentials are required to access this endpoint.",
    403: "You do not have permission to access the requested resource.",
    404: "The requested page or API endpoint could not be found on this server.",
    405: "The HTTP method used is not supported by this endpoint.",
    409: "The request conflicts with the current state of the server.",
    422: "The request parameters, query string, or payload failed schema validation.",
    429: (
        "Too many requests have been received in a short period. Please wait and"
        " try again."
    ),
    500: (
        "An unexpected error occurred while processing your request. Please try"
        " again later."
    ),
    501: "This feature or endpoint is not implemented on this server.",
    502: "The server received an invalid response from an upstream gateway.",
    503: "The service is temporarily unavailable. Please try again in a few moments.",
}


MAX_INPUT_DISPLAY_LENGTH = 60


def _format_location(loc: object) -> str:
    """Format Pydantic error location sequence into a readable field path."""
    if isinstance(loc, (list, tuple)) and loc:
        return " -> ".join(str(part) for part in loc)

    return str(loc) if loc else "(unknown)"


def _format_input_value(raw_input: object) -> str:
    """Format and truncate raw input value safely for HTML table presentation."""
    if raw_input is None:
        return "None"

    raw_str = str(raw_input)
    if len(raw_str) > MAX_INPUT_DISPLAY_LENGTH:
        return f"{raw_str[: MAX_INPUT_DISPLAY_LENGTH - 3]}..."

    return raw_str


def format_validation_error(err: Mapping[str, object]) -> dict[str, str]:
    """Format a single Pydantic error dictionary into a table-friendly item.

    Args:
        err: Pydantic validation error dictionary.

    Returns:
        Dictionary containing field, message, type, and formatted input value.
    """
    return {
        "field": _format_location(err.get("loc", ())),
        "message": str(err.get("msg", "Validation error")),
        "type": str(err.get("type", "value_error")),
        "input": _format_input_value(err.get("input")),
    }


def _resolve_error_title(status_code: int) -> str:
    """Resolve human-readable title for an HTTP status code."""
    return _HTTP_STATUS_TITLES.get(status_code, f"{status_code} - HTTP Error")


def _resolve_error_message(status_code: int) -> str:
    """Resolve human-readable explanation message for an HTTP status code."""
    return _HTTP_STATUS_MESSAGES.get(
        status_code,
        "An HTTP error occurred while processing your request.",
    )


def _build_http_error_context(exc: StarletteHTTPException) -> dict[str, object]:
    """Build template context dictionary for an HTTP exception.

    Args:
        exc: Starlette HTTP exception instance.

    Returns:
        Dictionary containing template context variables.
    """
    status_code = exc.status_code
    title = _resolve_error_title(status_code)
    message = _resolve_error_message(status_code)
    detail_str = str(exc.detail) if exc.detail else None

    return {
        "status_code": status_code,
        "error_title": title,
        "error_message": message,
        "error_detail": detail_str,
    }


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> Response:
    """Handle Starlette and FastAPI HTTP exceptions with content negotiation.

    Args:
        request: Incoming HTTP request.
        exc: Raised HTTP exception.

    Returns:
        Content-negotiated HTML or JSON HTTP response.
    """
    headers = dict(exc.headers) if exc.headers else {}
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)

    data: dict[str, object] = {"detail": exc.detail}
    context = _build_http_error_context(exc)
    return negotiate_response(
        request,
        data,
        "error.html",
        context=context,
        status_code=exc.status_code,
        headers=headers,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> Response:
    """Handle Pydantic request validation exceptions with content negotiation.

    Args:
        request: Incoming HTTP request.
        exc: Raised request validation exception.

    Returns:
        Content-negotiated HTML or JSON HTTP 422 response.
    """
    errors_list: list[dict[str, object]] = jsonable_encoder(exc.errors())
    data: dict[str, object] = {"detail": errors_list}
    formatted_errors = [format_validation_error(err) for err in errors_list]

    context: dict[str, object] = {
        "status_code": 422,
        "error_title": _resolve_error_title(422),
        "error_message": _resolve_error_message(422),
        "validation_errors": formatted_errors,
    }
    return negotiate_response(
        request,
        data,
        "error.html",
        context=context,
        status_code=422,
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> Response:
    """Handle unhandled 500 server exceptions with content negotiation.

    Server-side logs capture the exception and stack trace while the client
    receives a sanitized generic error message in either format to prevent
    information leakage (CodeQL Alert #14).

    Args:
        request: Incoming HTTP request.
        exc: Raised unhandled exception.

    Returns:
        Content-negotiated HTML or JSON HTTP 500 response.
    """
    logger.error(
        "Unhandled server exception processing %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    data: dict[str, object] = {"detail": "Internal Server Error"}
    context: dict[str, object] = {
        "status_code": 500,
        "error_title": _resolve_error_title(500),
        "error_message": _resolve_error_message(500),
    }
    return negotiate_response(
        request,
        data,
        "error.html",
        context=context,
        status_code=500,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register content-negotiated exception handlers on a FastAPI application.

    Args:
        app: FastAPI application instance.
    """
    app.exception_handler(StarletteHTTPException)(http_exception_handler)
    app.exception_handler(RequestValidationError)(validation_exception_handler)
    app.exception_handler(Exception)(unhandled_exception_handler)
