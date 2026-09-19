"""Production synchronization dispatching and management.

Provides unified dispatch strategies across Web API, GitHub Actions workflow
dispatch, and Render background worker/cron jobs.
"""

from __future__ import annotations

import os
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import click
import httpx

from ecu_hockey_calendar.cli.console import get_console, print_error, print_success
from ecu_hockey_calendar.version import __version__

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_PROD_API_URL = "https://ecu-hockey-api.onrender.com"
DEFAULT_GITHUB_REPO = "bdperkin/ecu-hockey-calendar"
DEFAULT_GITHUB_WORKFLOW = "schedule-sync.yml"
DEFAULT_GITHUB_REF = "main"
DEFAULT_RENDER_SERVICE_NAME = "ecu-hockey-worker"
DEFAULT_TIMEOUT = 30.0

DEFAULT_USER_AGENT = (
    f"ECUHockeyCLI/{__version__} (+https://github.com/bdperkin/ecu-hockey-calendar)"
)


def resolve_admin_token(token: str | None) -> str | None:
    """Resolve administrative Bearer token from argument or environment."""
    return (
        token
        or os.environ.get("ECU_HOCKEY_ADMIN_TOKEN")
        or os.environ.get("ADMIN_API_TOKEN")
    )


def resolve_github_token(token: str | None) -> str | None:
    """Resolve GitHub personal access token or actions token."""
    return token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def resolve_render_credentials(
    token: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Resolve Render API key, service ID, and deploy hook URL."""
    api_key = token or os.environ.get("RENDER_API_KEY")
    service_id = os.environ.get("RENDER_SERVICE_ID")
    deploy_hook = os.environ.get("DEPLOY_HOOK_URL") or os.environ.get(
        "RENDER_DEPLOY_HOOK_URL",
    )
    return api_key, service_id, deploy_hook


def _has_render_creds(token: str | None) -> bool:
    """Check whether any Render API key or deploy hook credentials exist."""
    api_key, _, deploy_hook = resolve_render_credentials(token)
    return bool(api_key or deploy_hook)


def _detect_auto_method(token: str | None) -> str:
    """Detect default production dispatch method from available credentials."""
    if resolve_admin_token(token):
        return "api"

    if resolve_github_token(token):
        return "github"

    if _has_render_creds(token):
        return "render"

    return "api"


def resolve_production_method(method: str | None, token: str | None) -> str:
    """Resolve effective production sync dispatch method.

    Args:
        method: User-specified method ('auto', 'api', 'github', 'render') or None.
        token: Explicit token argument passed via CLI.

    Returns:
        Canonical method name ('api', 'github', or 'render').
    """
    if method and method.strip().lower() != "auto":
        return method.strip().lower()

    return _detect_auto_method(token)


def _bool_str(val: bool) -> str:
    """Convert boolean value to lowercase string 'true' or 'false'."""
    return "true" if val else "false"


def _build_github_payload(
    ref: str,
    source_code: str,
    *,
    dry_run: bool,
    notify: bool,
    notify_individual: bool,
    season: str | None,
) -> dict[str, Any]:
    """Construct JSON request body for GitHub Actions workflow dispatch."""
    return {
        "ref": ref,
        "inputs": {
            "source": source_code.lower() if source_code else "all",
            "notify": _bool_str(notify),
            "notify_individual": _bool_str(notify_individual),
            "dry_run": _bool_str(dry_run),
            "season": season or "",
        },
    }


def _handle_github_response(resp: httpx.Response, repo: str, workflow: str) -> None:
    """Handle non-success HTTP response from GitHub dispatch endpoint."""
    if resp.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        msg = (
            f"GitHub authentication failed ({resp.status_code}): "
            "Ensure token has 'actions:write' permission."
        )
        print_error(msg)
        err_msg = "Authentication failed for GitHub workflow dispatch."
        raise click.ClickException(err_msg)

    if resp.status_code == HTTPStatus.NOT_FOUND:
        msg = f"GitHub workflow or repository not found ({repo} / {workflow})."
        print_error(msg)
        raise click.ClickException(msg)

    resp.raise_for_status()


def _render_github_success(repo: str, workflow: str, ref: str, source: str) -> None:
    """Display Rich confirmation panel for dispatched GitHub Actions workflow."""
    console = get_console()
    run_url = f"https://github.com/{repo}/actions/workflows/{workflow}"
    print_success(
        "GitHub Actions workflow dispatched successfully: Workflow run requested.",
    )
    console.print(f"  [bold]Workflow:[/bold]      [cyan]{workflow}[/cyan]")
    console.print(f"  [bold]Repository:[/bold]    [cyan]{repo}[/cyan]")
    console.print(f"  [bold]Branch/Ref:[/bold]    [cyan]{ref}[/cyan]")
    console.print(f"  [bold]Source:[/bold]        [cyan]{source}[/cyan]")
    console.print(f"  [bold]Workflow Runs:[/bold] [dim]{run_url}[/dim]")


def _resolve_github_target(
    repo: str | None,
    workflow: str | None,
    ref: str | None,
) -> tuple[str, str, str]:
    """Resolve target repository, workflow name, and git reference."""
    r = repo or os.environ.get("GITHUB_REPOSITORY", DEFAULT_GITHUB_REPO)
    w = workflow or DEFAULT_GITHUB_WORKFLOW
    b = ref or os.environ.get("GITHUB_REF", DEFAULT_GITHUB_REF)
    return r, w, b


def _post_github_dispatch(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    repo: str,
    workflow: str,
) -> None:
    """Send POST request to trigger GitHub Actions workflow dispatch."""
    resp = client.post(url, headers=headers, json=payload)
    _handle_github_response(resp, repo, workflow)


def dispatch_github_sync(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-locals
    *,
    token: str | None = None,
    repo: str | None = None,
    workflow: str | None = None,
    ref: str | None = None,
    source_code: str = "all",
    dry_run: bool = False,
    notify: bool = True,
    notify_individual: bool = False,
    season: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Dispatch schedule-sync workflow via GitHub Actions API."""
    resolved_token = resolve_github_token(token)
    if not resolved_token:
        auth_msg = (
            "Authentication required: GitHub token is required for workflow dispatch.\n"
            "Provide --token <TOKEN> or set GITHUB_TOKEN (or GH_TOKEN)."
        )
        print_error(auth_msg)
        err_msg = "Authentication failed for GitHub workflow dispatch."
        raise click.ClickException(err_msg)

    r, w, b = _resolve_github_target(repo, workflow, ref)
    get_console().print(
        f"Target: [bold cyan]Production GitHub Actions ({r} / {w})[/bold cyan]\n",
    )
    url = f"https://api.github.com/repos/{r}/actions/workflows/{w}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {resolved_token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    payload = _build_github_payload(
        b,
        source_code,
        dry_run=dry_run,
        notify=notify,
        notify_individual=notify_individual,
        season=season,
    )
    spinner_text = (
        "[bold #fec923]Dispatching GitHub Actions workflow dispatch "
        "request...[/bold #fec923]"
    )
    with get_console().status(spinner_text, spinner="dots"):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT, transport=transport) as client:
                _post_github_dispatch(
                    client,
                    url,
                    headers=headers,
                    payload=payload,
                    repo=r,
                    workflow=w,
                )
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            print_error(f"Failed to dispatch GitHub Actions workflow: {exc}")
            raise click.ClickException(str(exc)) from exc

    _render_github_success(r, w, b, source_code or "all")
    return {
        "status": "accepted",
        "method": "github",
        "repository": r,
        "workflow": w,
        "ref": b,
        "run_url": f"https://github.com/{r}/actions/workflows/{w}",
    }


def _extract_service_id_from_dict(item: object) -> str | None:
    """Extract service ID from single dictionary item."""
    if isinstance(item, dict):
        srv = item.get("service")
        if isinstance(srv, dict):
            sid = srv.get("id")
            return str(sid) if sid else None

    return None


def _extract_service_id_from_list(data: object) -> str | None:
    """Extract first service ID matching search results."""
    if isinstance(data, list) and data:
        return _extract_service_id_from_dict(data[0])

    return None


def _query_render_service_id(
    client: httpx.Client,
    service_name: str,
    api_key: str,
) -> str | None:
    """Look up Render service ID by service name."""
    resp = client.get(
        "https://api.render.com/v1/services",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={"name": service_name, "limit": 5},
    )
    if resp.status_code != HTTPStatus.OK:
        return None

    return _extract_service_id_from_list(resp.json())


def _extract_deploy_id(data: object) -> str:
    """Extract deployment ID from deploy hook JSON payload."""
    if isinstance(data, dict):
        deploy_data = data.get("deploy")
        if isinstance(deploy_data, dict):
            return str(deploy_data.get("id", "N/A"))

    return "N/A"


def _render_deploy_hook(
    client: httpx.Client,
    deploy_hook_url: str,
) -> dict[str, Any]:
    """Trigger deployment or worker run via Render deploy hook URL."""
    resp = client.post(
        deploy_hook_url,
        headers={"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT},
    )
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    deploy_id = _extract_deploy_id(data)

    console = get_console()
    print_success("Render deploy hook triggered successfully: Service run initiated.")
    console.print(f"  [bold]Deploy ID:[/bold]     [cyan]{deploy_id}[/cyan]")
    console.print(f"  [bold]Deploy Hook:[/bold]   [dim]{deploy_hook_url}[/dim]")
    return {
        "status": "accepted",
        "method": "render",
        "deploy_id": deploy_id,
        "hook_url": deploy_hook_url,
    }


def _handle_render_api_error(resp: httpx.Response, service_id: str) -> None:
    """Raise appropriate ClickException for Render API HTTP errors."""
    if resp.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        msg = (
            f"Render API authentication failed ({resp.status_code}): "
            "Invalid RENDER_API_KEY."
        )
        print_error(msg)
        err_msg = "Authentication failed for Render API."
        raise click.ClickException(err_msg)

    if resp.status_code == HTTPStatus.NOT_FOUND:
        msg = f"Render service '{service_id}' not found."
        print_error(msg)
        raise click.ClickException(msg)

    resp.raise_for_status()


def _extract_job_meta(data: object) -> tuple[str, str]:
    """Extract job ID and execution status from Render job response."""
    if isinstance(data, dict):
        return str(data.get("id", "N/A")), str(data.get("status", "created"))

    return "N/A", "created"


def _render_job_api(
    client: httpx.Client,
    service_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Trigger cron job execution via Render REST API."""
    url = f"https://api.render.com/v1/services/{service_id}/jobs"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    resp = client.post(url, headers=headers, json={})
    _handle_render_api_error(resp, service_id)

    job_id, job_status = _extract_job_meta(resp.json())
    console = get_console()
    print_success("Render cron job dispatched successfully: Job execution initiated.")
    console.print(f"  [bold]Job ID:[/bold]        [cyan]{job_id}[/cyan]")
    console.print(f"  [bold]Service ID:[/bold]    [cyan]{service_id}[/cyan]")
    console.print(f"  [bold]Status:[/bold]        [green]{job_status}[/green]")
    console.print(
        "  [bold]Dashboard:[/bold]     [dim]https://dashboard.render.com/[/dim]",
    )
    return {
        "status": "accepted",
        "method": "render",
        "job_id": job_id,
        "service_id": service_id,
    }


def _resolve_render_target(
    client: httpx.Client,
    api_key: str,
    service_id: str | None,
) -> str:
    """Resolve and validate active Render service ID."""
    sid = service_id or _query_render_service_id(
        client,
        DEFAULT_RENDER_SERVICE_NAME,
        api_key,
    )
    if not sid:
        err_msg = (
            f"Render service '{DEFAULT_RENDER_SERVICE_NAME}' could not be located.\n"
            "Set RENDER_SERVICE_ID explicitly."
        )
        print_error(err_msg)
        raise click.ClickException(err_msg)

    return sid


def _execute_render_request(
    client: httpx.Client,
    api_key: str | None,
    sid: str | None,
    hook_url: str | None,
) -> dict[str, Any]:
    """Route Render request to deploy hook or job API."""
    if hook_url and not api_key:
        return _render_deploy_hook(client, hook_url)

    if not api_key:
        auth_msg = (
            "Authentication required: Render API key or deploy hook is required.\n"
            "Provide --token <KEY> or set RENDER_API_KEY (or DEPLOY_HOOK_URL)."
        )
        print_error(auth_msg)
        err_msg = "Authentication failed for Render job trigger."
        raise click.ClickException(err_msg)

    target_sid = _resolve_render_target(client, api_key, sid)
    return _render_job_api(client, target_sid, api_key)


def dispatch_render_sync(
    *,
    token: str | None = None,
    service_id: str | None = None,
    deploy_hook_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Trigger production worker execution on Render."""
    api_key, resolved_service_id, resolved_hook = resolve_render_credentials(token)
    hook_url = deploy_hook_url or resolved_hook
    sid = service_id or resolved_service_id

    get_console().print(
        "Target: [bold cyan]Production Render Worker (ecu-hockey-worker)[/bold cyan]\n",
    )

    with get_console().status(
        "[bold #fec923]Dispatching Render execution request...[/bold #fec923]",
        spinner="dots",
    ):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT, transport=transport) as client:
                return _execute_render_request(client, api_key, sid, hook_url)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            print_error(f"Failed to trigger Render worker: {exc}")
            raise click.ClickException(str(exc)) from exc


def dispatch_production_sync(  # noqa: PLR0913 # pylint: disable=too-many-arguments
    *,
    method: str = "auto",
    api_url: str = DEFAULT_PROD_API_URL,
    token: str | None = None,
    source_code: str = "all",
    dry_run: bool = False,
    notify: bool = True,
    notify_individual: bool = False,
    season: str | None = None,
    transport: httpx.BaseTransport | None = None,
    execute_remote_fn: Callable[..., None] | None = None,
) -> None:
    """Route and dispatch production synchronization request.

    Args:
        method: Dispatch strategy ('auto', 'api', 'github', 'render').
        api_url: Target API URL for Web API method.
        token: Optional authentication Bearer token or API key.
        source_code: Specific ingestion source code filter.
        dry_run: If True, crawl and reconcile without persisting.
        notify: If True, dispatch webhook notifications.
        notify_individual: If True, alert for each fixture.
        season: Optional season filter string.
        transport: Optional HTTP transport for testing.
        execute_remote_fn: Optional callable to execute remote API sync.
    """
    effective_method = resolve_production_method(method, token)
    if effective_method == "github":
        dispatch_github_sync(
            token=token,
            source_code=source_code,
            dry_run=dry_run,
            notify=notify,
            notify_individual=notify_individual,
            season=season,
            transport=transport,
        )
        return

    if effective_method == "render":
        dispatch_render_sync(token=token, transport=transport)
        return

    # Default to Web API trigger
    if execute_remote_fn is not None:
        execute_remote_fn(
            api_url=api_url,
            token=token,
            source_code=source_code,
            is_production=True,
        )


__all__ = [
    "DEFAULT_GITHUB_REF",
    "DEFAULT_GITHUB_REPO",
    "DEFAULT_GITHUB_WORKFLOW",
    "DEFAULT_PROD_API_URL",
    "DEFAULT_RENDER_SERVICE_NAME",
    "dispatch_github_sync",
    "dispatch_production_sync",
    "dispatch_render_sync",
    "resolve_admin_token",
    "resolve_github_token",
    "resolve_production_method",
    "resolve_render_credentials",
]
