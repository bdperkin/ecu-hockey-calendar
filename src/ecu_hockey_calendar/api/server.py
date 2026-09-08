"""Server runner utility for ECU Hockey Calendar & Data Service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from fastapi import FastAPI


def run_server(
    app: FastAPI | str = "ecu_hockey_calendar.api.app:create_app",
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    reload: bool = False,
    factory: bool = True,
) -> None:
    """Run the FastAPI service using Uvicorn ASGI server.

    Args:
        app: FastAPI instance or import string.
        host: Network interface host to bind to.
        port: TCP port number to listen on.
        reload: Enable auto-reload on code changes (development only).
        factory: True if app is an importable application factory callable.
    """
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        factory=factory,
    )
