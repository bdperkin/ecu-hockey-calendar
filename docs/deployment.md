# Production Deployment & Hosting Architecture

This guide outlines deployment architectures, operational best practices, containerization, and hosting evaluations for running `ecu-hockey-calendar` in production.

For the comprehensive hosting platform evaluation, comparison matrices, and tactical anti-bot mitigations, refer to the root [DEPLOYMENT.md](https://github.com/bdperkin/ecu-hockey-calendar/blob/main/DEPLOYMENT.md).

## 1. Workload Architecture

The production environment separates concerns into two distinct roles:

1. **Calendar & Data REST API Service**:

   - Built on FastAPI and served by Uvicorn.
   - Provides live RFC 5545 iCalendar subscriptions (`/calendar.ics`), Webcal feeds, public JSON/CSV feeds, and health probes (`/health`).
   - Requires valid HTTPS/TLS termination for calendar client compatibility (Apple, Google, Outlook).

2. **Scraper & Synchronization Background Worker**:

   - Executes the automated ingestion pipeline across registered sources (`ecuhockey`, `acchockey`, tickets, Instagram).
   - Reconciles conflicting fixtures, detects state changes, persists records to the database, and dispatches webhook notifications (Discord, Slack, Telegram).
   - Can be run as a cron job or background daemon.

## 2. Containerized Deployment

Pre-built multi-architecture container images (`linux/amd64`, `linux/arm64`) are automatically published to the GitHub Container Registry (`ghcr.io/bdperkin/ecu-hockey-calendar`) on tagged releases and pushes to `main`.

### 2.1. Pulling and Running from GHCR

```bash
# Pull published container image
docker pull ghcr.io/bdperkin/ecu-hockey-calendar:latest

# Launch container with local port binding
docker run -d --name ecu-hockey -p 8000:8000 ghcr.io/bdperkin/ecu-hockey-calendar:latest
```

A production-ready multi-stage `Dockerfile` and `docker-compose.yml` orchestration configuration are included in the repository root.

### 2.2. Quick Container Launch with Docker Compose

```bash
# Initialize environment configuration
cp .env.example .env

# Start API service, PostgreSQL, and Background Worker using published image
docker compose up -d

# Or force local container build
docker compose up -d --build

# Check container status
docker compose ps

# Verify API health
curl -s http://localhost:8000/health | jq .
```

### 2.3. Database Schema Migrations

Database schema migrations are managed via Alembic:

```bash
# Run migrations inside running container
docker compose exec api alembic upgrade head
```

### 2.4. Continuous Deployment via GitHub Actions

The repository includes an automated Continuous Deployment workflow (`.github/workflows/deploy.yml`):

- **Automatic Trigger**: Executes upon successful completion of the `Docker` build workflow on `main` (deploying `edge`), or on release publication (`vX.Y.Z`).
- **Manual Trigger**: Supports `workflow_dispatch` with environment selection (`production` or `staging`) and custom image tags.
- **Pre-Deploy Migrations**: Runs schema migrations (`alembic upgrade head`) before serving traffic to prevent incompatible states.
- **Automated Health Verification**: Polls `/health` for up to 5 minutes to ensure service stability before completing the deployment.

To configure CD:

1. In GitHub Repository **Settings** > **Environments**, create the `production` environment.
2. Add secrets `DEPLOY_HOOK_URL` (Render deploy hook) and `PRODUCTION_URL` (public HTTPS URL).

### 2.5. Turnkey Render Blueprint

Deploy the entire production stack (FastAPI service, PostgreSQL database, and 6-hour cron worker) with a single click using [`render.yaml`](https://github.com/bdperkin/ecu-hockey-calendar/blob/main/render.yaml) in the Render dashboard.

## 3. Hosting Platform Recommendations

- **Recommended PaaS Stack**: **Railway** or **Render** with managed PostgreSQL and scheduled background worker jobs.
- **Low-Cost Single-Node**: **Fly.io** with persistent NVMe volume for SQLite storage (`/data/ecu_hockey.db`).
- **Serverless / Enterprise**: **AWS Lambda** (container image packaged to ECR) triggered by Amazon EventBridge rules.

## 4. Key Operational Considerations

- **SSL/TLS Termination**: Calendar clients strictly mandate trusted CA-signed TLS certificates. Use managed certificates (Let's Encrypt / Cloudflare) provided automatically by Render, Railway, or Fly.io.
- **Instagram Anti-Bot Mitigation**: Rotate residential proxies via `PROXY_URL`, implement exponential backoff, and rely on non-blocking fallback so scraper hiccups never impede primary fixture updates.
- **Database Persistence**: Prefer managed PostgreSQL for multi-replica concurrency and automated point-in-time recovery.

## 5. Operational Runbook & Emergency Rollback

If a deployment fails or causes degradation:

1. **Review CI Summary**: Check GitHub Actions step summary for deployment and health check status.
2. **Inspect Logs**: Check hosting provider logs (Render / Railway / Fly.io) for Python traceback or migration errors.
3. **Rollback**: In the hosting dashboard, click **Rollback to this deploy** on the last healthy version, or dispatch `.github/workflows/deploy.yml` with the previous image tag.
