"""Unit tests for production synchronization dispatching and CLI integration."""

from __future__ import annotations

# pylint: disable=protected-access,unused-argument,too-many-public-methods,redefined-outer-name,too-many-lines
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import click
import httpx
import pytest
from click.testing import CliRunner

from ecu_hockey_calendar.cli.main import cli
from ecu_hockey_calendar.cli.production import (
    DEFAULT_GITHUB_REF,
    DEFAULT_GITHUB_REPO,
    DEFAULT_GITHUB_WORKFLOW,
    DEFAULT_PROD_API_URL,
    DEFAULT_RENDER_SERVICE_NAME,
    _bool_str,
    _build_github_payload,
    _detect_auto_method,
    _extract_deploy_id,
    _extract_job_meta,
    _extract_service_id_from_dict,
    _extract_service_id_from_list,
    _has_render_creds,
    _resolve_github_target,
    dispatch_github_sync,
    dispatch_production_sync,
    dispatch_render_sync,
    resolve_admin_token,
    resolve_github_token,
    resolve_production_method,
    resolve_render_credentials,
)
from ecu_hockey_calendar.cli.sync import (
    _apply_prod_defaults,
    _handle_remote_sync_result,
    _maybe_dispatch_remote_sync,
    _populate_ctx_params,
    _render_sync_details,
    _render_sync_url,
    _resolve_prod_flag,
    _resolve_remote_credentials,
)


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Click test runner fixture."""
    return CliRunner()


class TestTokenResolution:
    """Tests for credential resolution helpers."""

    def test_resolve_admin_token_arg(self) -> None:
        """Verify explicit token takes precedence."""
        assert resolve_admin_token("arg-token") == "arg-token"

    def test_resolve_admin_token_ecu_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify ECU_HOCKEY_ADMIN_TOKEN resolution."""
        monkeypatch.setenv("ECU_HOCKEY_ADMIN_TOKEN", "ecu-env-token")
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        assert resolve_admin_token(None) == "ecu-env-token"

    def test_resolve_admin_token_admin_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify ADMIN_API_TOKEN fallback resolution."""
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.setenv("ADMIN_API_TOKEN", "admin-env-token")
        assert resolve_admin_token(None) == "admin-env-token"

    def test_resolve_admin_token_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify None when no admin token is available."""
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        assert resolve_admin_token(None) is None

    def test_resolve_github_token_arg(self) -> None:
        """Verify explicit GitHub token takes precedence."""
        assert resolve_github_token("gh-arg") == "gh-arg"

    def test_resolve_github_token_gh_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify GH_TOKEN resolution."""
        monkeypatch.setenv("GH_TOKEN", "gh-env-token")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert resolve_github_token(None) == "gh-env-token"

    def test_resolve_github_token_github_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify GITHUB_TOKEN fallback resolution."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "github-env-token")
        assert resolve_github_token(None) == "github-env-token"

    def test_resolve_github_token_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify None when no GitHub token is available."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert resolve_github_token(None) is None

    def test_resolve_render_credentials_arg(self) -> None:
        """Verify explicit render token sets api_key."""
        api_key, service_id, hook = resolve_render_credentials("rnd-key")
        assert api_key == "rnd-key"  # pragma: allowlist secret
        assert service_id is None
        assert hook is None

    def test_resolve_render_credentials_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify resolution from Render environment variables."""
        monkeypatch.setenv("RENDER_API_KEY", "rnd-env-key")
        monkeypatch.setenv("RENDER_SERVICE_ID", "srv-12345")
        monkeypatch.setenv("DEPLOY_HOOK_URL", "https://api.render.com/deploy/srv-123")
        api_key, service_id, hook = resolve_render_credentials(None)
        assert api_key == "rnd-env-key"  # pragma: allowlist secret
        assert service_id == "srv-12345"
        assert hook == "https://api.render.com/deploy/srv-123"

    def test_resolve_render_credentials_render_hook_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify RENDER_DEPLOY_HOOK_URL fallback resolution."""
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
        monkeypatch.delenv("DEPLOY_HOOK_URL", raising=False)
        monkeypatch.setenv(
            "RENDER_DEPLOY_HOOK_URL",
            "https://api.render.com/deploy/srv-fallback",
        )
        api_key, service_id, hook = resolve_render_credentials(None)
        assert api_key is None
        assert service_id is None
        assert hook == "https://api.render.com/deploy/srv-fallback"

    def test_has_render_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify _has_render_creds detection."""
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        monkeypatch.delenv("DEPLOY_HOOK_URL", raising=False)
        monkeypatch.delenv("RENDER_DEPLOY_HOOK_URL", raising=False)
        assert _has_render_creds(None) is False
        assert _has_render_creds("key") is True
        monkeypatch.setenv("DEPLOY_HOOK_URL", "https://render.hook")
        assert _has_render_creds(None) is True


class TestMethodResolution:
    """Tests for production sync method determination."""

    def test_detect_auto_method_admin_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify auto-detection selects 'api' when admin token is present."""
        monkeypatch.setenv("ECU_HOCKEY_ADMIN_TOKEN", "token")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        assert _detect_auto_method(None) == "api"

    def test_detect_auto_method_github_token(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify auto-detection selects 'github' when GitHub token is present."""
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "gh-tok")
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        assert _detect_auto_method(None) == "github"

    def test_detect_auto_method_render_creds(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify auto-detection selects 'render' when Render creds are present."""
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("RENDER_API_KEY", "rnd-key")
        assert _detect_auto_method(None) == "render"

    def test_detect_auto_method_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify auto-detection defaults to 'api' when no creds are present."""
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        monkeypatch.delenv("DEPLOY_HOOK_URL", raising=False)
        monkeypatch.delenv("RENDER_DEPLOY_HOOK_URL", raising=False)
        assert _detect_auto_method(None) == "api"

    def test_resolve_production_method_explicit(self) -> None:
        """Verify explicit methods are normalized and preserved."""
        assert resolve_production_method("github", None) == "github"
        assert resolve_production_method(" RENDER ", None) == "render"
        assert resolve_production_method("API", None) == "api"

    def test_resolve_production_method_auto(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify 'auto' triggers credential-based detection."""
        monkeypatch.setenv("GITHUB_TOKEN", "gh-tok")
        monkeypatch.delenv("ECU_HOCKEY_ADMIN_TOKEN", raising=False)
        monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
        assert resolve_production_method("auto", None) == "github"
        assert resolve_production_method(None, None) == "github"


class TestHelperFunctions:
    """Tests for serialization and parsing helper utilities."""

    def test_bool_str(self) -> None:
        """Verify boolean to lowercase string conversion."""
        assert _bool_str(val=True) == "true"
        assert _bool_str(val=False) == "false"

    def test_build_github_payload(self) -> None:
        """Verify GitHub Actions workflow dispatch request payload structure."""
        payload = _build_github_payload(
            "main",
            "ECUHOCKEY",
            dry_run=True,
            notify=False,
            notify_individual=True,
            season="2026-2027",
        )
        assert payload == {
            "ref": "main",
            "inputs": {
                "source": "ecuhockey",
                "notify": "false",
                "notify_individual": "true",
                "dry_run": "true",
                "season": "2026-2027",
            },
        }

    def test_build_github_payload_defaults(self) -> None:
        """Verify payload when source is empty and season is None."""
        payload = _build_github_payload(
            "develop",
            "",
            dry_run=False,
            notify=True,
            notify_individual=False,
            season=None,
        )
        assert payload["inputs"]["source"] == "all"
        assert payload["inputs"]["season"] == ""

    def test_resolve_github_target_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify fallback repository, workflow, and ref."""
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_REF", raising=False)
        repo, workflow, ref = _resolve_github_target(None, None, None)
        assert repo == DEFAULT_GITHUB_REPO
        assert workflow == DEFAULT_GITHUB_WORKFLOW
        assert ref == DEFAULT_GITHUB_REF

    def test_resolve_github_target_env_and_args(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify environment variables and explicit arguments."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "env/repo")
        monkeypatch.setenv("GITHUB_REF", "refs/heads/release")
        repo, _workflow, ref = _resolve_github_target(None, None, None)
        assert repo == "env/repo"
        assert ref == "refs/heads/release"

        r, w, b = _resolve_github_target("my/repo", "custom.yml", "custom-ref")
        assert r == "my/repo"
        assert w == "custom.yml"
        assert b == "custom-ref"

    def test_extract_service_id_from_dict(self) -> None:
        """Verify service ID extraction from dictionary."""
        assert (
            _extract_service_id_from_dict({"service": {"id": "srv-123"}}) == "srv-123"
        )
        assert _extract_service_id_from_dict({"service": {}}) is None
        assert _extract_service_id_from_dict({"other": 1}) is None
        assert _extract_service_id_from_dict("not-a-dict") is None

    def test_extract_service_id_from_list(self) -> None:
        """Verify service ID extraction from search response list."""
        data = [{"service": {"id": "srv-999"}}]
        assert _extract_service_id_from_list(data) == "srv-999"
        assert _extract_service_id_from_list([]) is None
        assert _extract_service_id_from_list("not-a-list") is None

    def test_extract_deploy_id(self) -> None:
        """Verify deploy ID extraction from webhook response."""
        assert _extract_deploy_id({"deploy": {"id": "dep-456"}}) == "dep-456"
        assert _extract_deploy_id({"deploy": {}}) == "N/A"
        assert _extract_deploy_id("invalid") == "N/A"

    def test_extract_job_meta(self) -> None:
        """Verify job metadata extraction from Render job response."""
        meta = _extract_job_meta({"id": "job-789", "status": "succeeded"})
        assert meta == ("job-789", "succeeded")
        assert _extract_job_meta({}) == ("N/A", "created")
        assert _extract_job_meta("invalid") == ("N/A", "created")


class TestGitHubDispatch:
    """Tests for GitHub Actions workflow dispatch execution."""

    def test_dispatch_github_sync_missing_token(self) -> None:
        """Verify error when no GitHub token is provided."""
        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(token=None)

        assert "Authentication failed for GitHub workflow dispatch" in str(
            exc_info.value,
        )

    def test_dispatch_github_sync_success(self) -> None:
        """Verify successful 204 response from GitHub dispatch endpoint."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert (
                request.url
                == "https://api.github.com/repos/bdperkin/ecu-hockey-calendar/actions/workflows/schedule-sync.yml/dispatches"
            )
            assert request.headers["Authorization"] == "Bearer mock-gh-token"
            return httpx.Response(status_code=HTTPStatus.NO_CONTENT)

        result = dispatch_github_sync(
            token="mock-gh-token",
            source_code="ecuhockey",
            dry_run=True,
            transport=httpx.MockTransport(handler),
        )
        assert result["status"] == "accepted"
        assert result["method"] == "github"
        assert result["repository"] == DEFAULT_GITHUB_REPO
        assert result["workflow"] == DEFAULT_GITHUB_WORKFLOW

    def test_dispatch_github_sync_auth_error_401(self) -> None:
        """Verify 401 unauthorized response raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.UNAUTHORIZED)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(
                token="bad-token",
                transport=httpx.MockTransport(handler),
            )

        assert "Authentication failed for GitHub workflow dispatch" in str(
            exc_info.value,
        )

    def test_dispatch_github_sync_auth_error_403(self) -> None:
        """Verify 403 forbidden response raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.FORBIDDEN)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(
                token="forbidden-token",
                transport=httpx.MockTransport(handler),
            )

        assert "Authentication failed for GitHub workflow dispatch" in str(
            exc_info.value,
        )

    def test_dispatch_github_sync_not_found_404(self) -> None:
        """Verify 404 not found response raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.NOT_FOUND)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(
                token="mock-token",
                transport=httpx.MockTransport(handler),
            )

        assert "GitHub workflow or repository not found" in str(exc_info.value)

    def test_dispatch_github_sync_http_status_error_500(self) -> None:
        """Verify generic 500 server error raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content=b"Server Error",
            )

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(
                token="mock-token",
                transport=httpx.MockTransport(handler),
            )

        assert "500" in str(exc_info.value)

    def test_dispatch_github_sync_request_error(self) -> None:
        """Verify network request error raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Network unreachable")

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_github_sync(
                token="mock-token",
                transport=httpx.MockTransport(handler),
            )

        assert "Network unreachable" in str(exc_info.value)


class TestRenderDispatch:
    """Tests for Render deploy hook and API job dispatching."""

    def test_dispatch_render_no_credentials(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify error when no Render credentials are provided."""
        monkeypatch.delenv("RENDER_API_KEY", raising=False)
        monkeypatch.delenv("DEPLOY_HOOK_URL", raising=False)
        monkeypatch.delenv("RENDER_DEPLOY_HOOK_URL", raising=False)
        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(token=None)

        assert "Authentication failed for Render job trigger" in str(exc_info.value)

    def test_dispatch_render_deploy_hook_success(self) -> None:
        """Verify triggering sync via Render deploy hook URL."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            return httpx.Response(
                status_code=HTTPStatus.OK,
                json={"deploy": {"id": "dep-abc-123"}},
            )

        result = dispatch_render_sync(
            deploy_hook_url="https://api.render.com/deploy/srv-123",
            transport=httpx.MockTransport(handler),
        )
        assert result["status"] == "accepted"
        assert result["method"] == "render"
        assert result["deploy_id"] == "dep-abc-123"

    def test_dispatch_render_deploy_hook_empty_response(self) -> None:
        """Verify deploy hook with 200 OK and empty response body."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.OK, content=b"")

        result = dispatch_render_sync(
            deploy_hook_url="https://api.render.com/deploy/srv-empty",
            transport=httpx.MockTransport(handler),
        )
        assert result["deploy_id"] == "N/A"

    def test_dispatch_render_job_api_with_service_id(self) -> None:
        """Verify triggering Render job via API with explicit service ID."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert (
                request.url == "https://api.render.com/v1/services/srv-target-123/jobs"
            )
            assert request.headers["Authorization"] == "Bearer mock-render-key"
            return httpx.Response(
                status_code=HTTPStatus.CREATED,
                json={"id": "job-xyz-789", "status": "created"},
            )

        result = dispatch_render_sync(
            token="mock-render-key",
            service_id="srv-target-123",
            transport=httpx.MockTransport(handler),
        )
        assert result["status"] == "accepted"
        assert result["method"] == "render"
        assert result["job_id"] == "job-xyz-789"
        assert result["service_id"] == "srv-target-123"

    def test_dispatch_render_job_api_service_lookup_success(self) -> None:
        """Verify service name lookup when service_id is not provided."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                assert "name=ecu-hockey-worker" in str(request.url)
                return httpx.Response(
                    status_code=HTTPStatus.OK,
                    json=[{"service": {"id": "srv-discovered-555"}}],
                )

            assert (
                request.url
                == "https://api.render.com/v1/services/srv-discovered-555/jobs"
            )
            return httpx.Response(
                status_code=HTTPStatus.CREATED,
                json={"id": "job-discovered-1", "status": "created"},
            )

        result = dispatch_render_sync(
            token="mock-render-key",
            transport=httpx.MockTransport(handler),
        )
        assert result["service_id"] == "srv-discovered-555"
        assert result["job_id"] == "job-discovered-1"

    def test_dispatch_render_job_api_service_lookup_not_found(self) -> None:
        """Verify error when service name lookup fails."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.OK, json=[])

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="mock-render-key",
                transport=httpx.MockTransport(handler),
            )

        err_sub = f"Render service '{DEFAULT_RENDER_SERVICE_NAME}' could not be located"
        assert err_sub in str(exc_info.value)

    def test_dispatch_render_job_api_service_lookup_http_error(self) -> None:
        """Verify error when service lookup returns non-200."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="mock-render-key",
                transport=httpx.MockTransport(handler),
            )

        assert "could not be located" in str(exc_info.value)

    def test_dispatch_render_job_api_auth_error_401(self) -> None:
        """Verify 401 response from Render jobs API raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.UNAUTHORIZED)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="bad-key",
                service_id="srv-123",
                transport=httpx.MockTransport(handler),
            )

        assert "Authentication failed for Render API" in str(exc_info.value)

    def test_dispatch_render_job_api_auth_error_403(self) -> None:
        """Verify 403 response from Render jobs API raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.FORBIDDEN)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="bad-key",
                service_id="srv-123",
                transport=httpx.MockTransport(handler),
            )

        assert "Authentication failed for Render API" in str(exc_info.value)

    def test_dispatch_render_job_api_not_found_404(self) -> None:
        """Verify 404 response from Render jobs API raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=HTTPStatus.NOT_FOUND)

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="mock-key",
                service_id="srv-nonexistent",
                transport=httpx.MockTransport(handler),
            )

        assert "Render service 'srv-nonexistent' not found" in str(exc_info.value)

    def test_dispatch_render_job_api_generic_error(self) -> None:
        """Verify generic 500 error raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                content=b"Server error",
            )

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="mock-key",
                service_id="srv-123",
                transport=httpx.MockTransport(handler),
            )

        assert "500" in str(exc_info.value)

    def test_dispatch_render_job_api_request_error(self) -> None:
        """Verify network error during Render execution raises click exception."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection timed out")

        with pytest.raises(click.ClickException) as exc_info:
            dispatch_render_sync(
                token="mock-key",
                service_id="srv-123",
                transport=httpx.MockTransport(handler),
            )

        assert "Connection timed out" in str(exc_info.value)


class TestProductionDispatchRouter:
    """Tests for dispatch_production_sync router."""

    def test_dispatch_production_sync_github(self) -> None:
        """Verify dispatch_production_sync routes to GitHub when method is 'github'."""
        with patch(
            "ecu_hockey_calendar.cli.production.dispatch_github_sync",
        ) as mock_gh:
            dispatch_production_sync(
                method="github",
                token="gh-token",
                source_code="ecuhockey",
                dry_run=True,
                notify=False,
                notify_individual=True,
                season="2026-2027",
            )
            mock_gh.assert_called_once_with(
                token="gh-token",
                source_code="ecuhockey",
                dry_run=True,
                notify=False,
                notify_individual=True,
                season="2026-2027",
                transport=None,
            )

    def test_dispatch_production_sync_render(self) -> None:
        """Verify dispatch_production_sync routes to Render when method is 'render'."""
        with patch(
            "ecu_hockey_calendar.cli.production.dispatch_render_sync",
        ) as mock_rnd:
            dispatch_production_sync(method="render", token="rnd-token")
            mock_rnd.assert_called_once_with(token="rnd-token", transport=None)

    def test_dispatch_production_sync_api(self) -> None:
        """Verify dispatch_production_sync routes to Web API by default."""
        mock_fn = MagicMock()
        dispatch_production_sync(
            method="api",
            api_url="https://custom.api",
            token="admin-token",
            source_code="all",
            execute_remote_fn=mock_fn,
        )
        mock_fn.assert_called_once_with(
            api_url="https://custom.api",
            token="admin-token",
            source_code="all",
            is_production=True,
        )

    def test_dispatch_production_sync_api_none_fn(self) -> None:
        """Verify no-op when execute_remote_fn is None."""
        dispatch_production_sync(method="api", execute_remote_fn=None)


class TestCliSyncHelpers:
    """Tests for sync.py helpers and details rendering."""

    def test_render_sync_url(self) -> None:
        """Verify _render_sync_url prints status URL when api_url is provided."""
        mock_console = MagicMock()
        _render_sync_url(mock_console, "https://remote.api/")
        mock_console.print.assert_called_once()
        assert "https://remote.api/api/v1/sync/status" in str(
            mock_console.print.call_args,
        )

        mock_console.reset_mock()
        _render_sync_url(mock_console, None)
        mock_console.print.assert_not_called()

    def test_render_sync_details(self) -> None:
        """Verify _render_sync_details prints cycle id, source, and timestamp."""
        payload = {
            "sync_cycle_id": "cycle-abc-123",
            "target_source": "ecuhockey",
            "timestamp": "2026-09-18T20:00:00Z",
        }
        with patch("ecu_hockey_calendar.cli.sync.get_console") as mock_get_console:
            mock_console = MagicMock()
            mock_get_console.return_value = mock_console
            _render_sync_details(payload, "https://remote.api")
            assert mock_console.print.call_count >= 3

    def test_handle_remote_sync_result_unsupported(self) -> None:
        """Verify warning printed when sync trigger is unsupported."""
        with patch("ecu_hockey_calendar.cli.sync.print_warning") as mock_warn:
            _handle_remote_sync_result({"status": "unsupported", "message": "No sync"})
            mock_warn.assert_called_once_with("No sync")

    def test_handle_remote_sync_result_success(self) -> None:
        """Verify success and details printed on successful remote sync."""
        with (
            patch("ecu_hockey_calendar.cli.sync.print_success") as mock_succ,
            patch("ecu_hockey_calendar.cli.sync._render_sync_details") as mock_det,
        ):
            _handle_remote_sync_result(
                {"status": "accepted", "message": "All good"},
                api_url="https://remote.api",
            )
            mock_succ.assert_called_once()
            mock_det.assert_called_once_with(
                {"status": "accepted", "message": "All good"},
                "https://remote.api",
            )

    def test_resolve_prod_flag(self) -> None:
        """Verify _resolve_prod_flag combinations."""
        assert _resolve_prod_flag(None, prod=True) is True
        assert _resolve_prod_flag(None, prod=False) is False

        ctx = click.Context(click.Command("test"))
        ctx.obj = {"prod": True}
        assert _resolve_prod_flag(ctx, prod=False) is True

        ctx.obj = {"prod": False}
        assert _resolve_prod_flag(ctx, prod=False) is False

    def test_apply_prod_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify production defaults application."""
        monkeypatch.setenv("ECU_HOCKEY_ADMIN_TOKEN", "env-admin-tok")
        url, tok = _apply_prod_defaults(None, None)
        assert url == DEFAULT_PROD_API_URL
        assert tok == "env-admin-tok"

        url2, tok2 = _apply_prod_defaults("https://my.api", "my-tok")
        assert url2 == "https://my.api"
        assert tok2 == "my-tok"

    def test_resolve_remote_credentials(self) -> None:
        """Verify _resolve_remote_credentials with and without prod."""
        ctx = click.Context(click.Command("test"))
        ctx.obj = {"api_url": "https://ctx.api", "token": "ctx-tok", "prod": False}
        url, tok = _resolve_remote_credentials(ctx, None, None, prod=False)
        assert url == "https://ctx.api"
        assert tok == "ctx-tok"

        url_p, tok_p = _resolve_remote_credentials(ctx, None, "arg-tok", prod=True)
        assert url_p == "https://ctx.api"
        assert tok_p == "arg-tok"

    def test_populate_ctx_params_prod(self) -> None:
        """Verify _populate_ctx_params sets prod in ctx.obj."""
        ctx = click.Context(click.Command("test"))
        _populate_ctx_params(ctx, None, None, None, prod=True)
        assert ctx.obj["prod"] is True

    def test_maybe_dispatch_remote_sync(self) -> None:
        """Verify _maybe_dispatch_remote_sync dispatch logic."""
        with patch(
            "ecu_hockey_calendar.cli.sync.dispatch_production_sync",
        ) as mock_prod:
            dispatched = _maybe_dispatch_remote_sync(
                is_prod=True,
                method="auto",
                api_url=None,
                token="tok",
                source_code="all",
                dry_run=False,
                notify=False,
                notify_individual=False,
                season=None,
            )
            assert dispatched is True
            mock_prod.assert_called_once()

        with patch("ecu_hockey_calendar.cli.sync._execute_remote_sync") as mock_exec:
            dispatched = _maybe_dispatch_remote_sync(
                is_prod=False,
                method="auto",
                api_url="https://remote.api",
                token="tok",
                source_code="all",
                dry_run=False,
                notify=False,
                notify_individual=False,
                season=None,
            )
            assert dispatched is True
            mock_exec.assert_called_once()

        dispatched = _maybe_dispatch_remote_sync(
            is_prod=False,
            method="auto",
            api_url=None,
            token="tok",
            source_code="all",
            dry_run=False,
            notify=False,
            notify_individual=False,
            season=None,
        )
        assert dispatched is False


class TestCliProductionCommands:
    """CLI end-to-end command tests with --prod flag and methods."""

    def test_sync_command_prod_web_api(self, runner: CliRunner) -> None:
        """Verify 'ecu-hockey sync --prod' targets production Web API."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {
            "status": "accepted",
            "sync_cycle_id": "prod-cycle-1",
            "message": "Production sync triggered",
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                ["sync", "--prod", "--token", "prod-secret-token"],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(
                DEFAULT_PROD_API_URL,
                token="prod-secret-token",
            )
            assert "Production Web API" in result.output
            assert "prod-cycle-1" in result.output

    def test_sync_command_production_alias(self, runner: CliRunner) -> None:
        """Verify '--production' long alias works identically."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {
            "status": "accepted",
            "message": "Triggered",
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                ["sync", "--production", "--token", "prod-secret-token"],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(
                DEFAULT_PROD_API_URL,
                token="prod-secret-token",
            )

    def test_root_prod_flag_sync(self, runner: CliRunner) -> None:
        """Verify root 'ecu-hockey --prod sync' propagates production target."""
        mock_client = MagicMock()
        mock_client.trigger_sync.return_value = {"status": "accepted"}

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                ["--prod", "sync", "--token", "prod-tok"],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(DEFAULT_PROD_API_URL, token="prod-tok")

    def test_sync_trigger_prod_github(self, runner: CliRunner) -> None:
        """Verify 'sync trigger --prod --method github' invokes GitHub."""
        with patch(
            "ecu_hockey_calendar.cli.production.dispatch_github_sync",
        ) as mock_gh:
            result = runner.invoke(
                cli,
                [
                    "sync",
                    "trigger",
                    "--prod",
                    "--method",
                    "github",
                    "--token",
                    "gh-token",
                ],
            )
            assert result.exit_code == 0
            mock_gh.assert_called_once()

    def test_sync_trigger_prod_render(self, runner: CliRunner) -> None:
        """Verify 'sync trigger --prod --method render' invokes Render."""
        with patch(
            "ecu_hockey_calendar.cli.production.dispatch_render_sync",
        ) as mock_rnd:
            result = runner.invoke(
                cli,
                [
                    "sync",
                    "trigger",
                    "--prod",
                    "--method",
                    "render",
                    "--token",
                    "rnd-token",
                ],
            )
            assert result.exit_code == 0
            mock_rnd.assert_called_once()

    def test_sync_status_prod(self, runner: CliRunner) -> None:
        """Verify 'ecu-hockey sync status --prod' queries production telemetry."""
        mock_client = MagicMock()
        mock_client.get_sync_status.return_value = {
            "current_status": "idle",
            "total_syncs": 42,
            "last_successful_sync": "2026-09-18T12:00:00Z",
            "last_sync": {
                "sync_cycle_id": "cycle-42",
                "status": "SUCCESS",
                "started_at": "2026-09-18T11:55:00Z",
                "duration_ms": 1500,
            },
            "sources": [],
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ) as mock_cls:
            result = runner.invoke(
                cli,
                ["sync", "status", "--prod", "--token", "prod-tok"],
            )
            assert result.exit_code == 0
            mock_cls.assert_called_once_with(DEFAULT_PROD_API_URL, token="prod-tok")
            assert "Remote API (https://ecu-hockey-api.onrender.com)" in result.output
            assert "cycle-42" in result.output

    def test_sync_status_prod_json(self, runner: CliRunner) -> None:
        """Verify 'ecu-hockey sync status --prod --json' outputs JSON."""
        mock_client = MagicMock()
        mock_client.get_sync_status.return_value = {
            "current_status": "idle",
            "total_syncs": 42,
        }

        with patch(
            "ecu_hockey_calendar.cli.sync.RemoteApiClient",
            return_value=mock_client,
        ):
            result = runner.invoke(
                cli,
                ["sync", "status", "--prod", "--json"],
            )
            assert result.exit_code == 0
            assert '"total_syncs": 42' in result.output
