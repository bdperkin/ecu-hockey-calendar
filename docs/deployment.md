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

A production-ready multi-stage `Dockerfile` and `docker-compose.yml` orchestration configuration are included in the repository root.

### 2.1. Quick Container Launch

```bash
# Initialize environment configuration
cp .env.example .env

# Start API service, PostgreSQL, and Background Worker
docker compose up -d --build

# Check container status
docker compose ps

# Verify API health
curl -s http://localhost:8000/health | jq .
```

### 2.2. Database Schema Migrations

Database schema migrations are managed via Alembic:

```bash
# Run migrations inside running container
docker compose exec api alembic upgrade head
```

## 3. Hosting Platform Recommendations

- **Recommended PaaS Stack**: **Railway** or **Render** with managed PostgreSQL and scheduled background worker jobs.
- **Low-Cost Single-Node**: **Fly.io** with persistent NVMe volume for SQLite storage (`/data/ecu_hockey.db`).
- **Serverless / Enterprise**: **AWS Lambda** (container image packaged to ECR) triggered by Amazon EventBridge rules.

## 4. Key Operational Considerations

- **SSL/TLS Termination**: Calendar clients strictly mandate trusted CA-signed TLS certificates. Use managed certificates (Let's Encrypt / Cloudflare) provided automatically by Render, Railway, or Fly.io.
- **Instagram Anti-Bot Mitigation**: Rotate residential proxies via `PROXY_URL`, implement exponential backoff, and rely on non-blocking fallback so scraper hiccups never impede primary fixture updates.
- **Database Persistence**: Prefer managed PostgreSQL for multi-replica concurrency and automated point-in-time recovery.
