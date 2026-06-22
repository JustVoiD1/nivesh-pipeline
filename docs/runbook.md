# Ingestion Pipeline Runbook

This runbook describes how to boot, configure, run, and maintain the Nivesh AI AMC Data Pipeline.

## System Pre-requisites

- Docker and Docker Compose
- Node.js 20+ (for local dashboard development)
- Python 3.12+ (for local pipeline development)

---

## Quick Start (Docker Orchestrated)

The easiest way to start the entire system (Database, Pipeline API, Dashboard) is using Docker Compose:

```bash
# Start all containers in the background
docker-compose up -d --build
```

This brings up:
1. **PostgreSQL** (`localhost:5432`): Hosts staging, classification, and published warehouse data.
2. **Pipeline API** (`localhost:8000`): FastAPI server handling triggers and database operations.
3. **Next.js Dashboard** (`localhost:3000`): Ingestion dashboard.

---

## Database Initial Setup

The database schema is initialized automatically when PostgreSQL boots via `scripts/init.sql`.

To inspect or query the database manually:
```bash
docker exec -it nivesh-postgres psql -U nivesh -d nivesh_pipeline
```

---

## Triggering an Ingestion Run

### Option A: Using the Dashboard (Recommended)
1. Navigate to the **Sources** tab (`http://localhost:3000/sources`).
2. Click **Run Scrape** on any configured AMC source (e.g. `sbi_mf`, `hdfc_mf`, `icici_prudential`).

### Option B: Using curl API directly
```bash
curl -X POST http://localhost:8000/pipeline/run/sbi_mf \
     -H "Content-Type: application/json" \
     -d '{"force_refresh": false}'
```

---

## Human-in-the-Loop Quarantine Queue Review

1. If a document receives a confidence score below the threshold ($< 85\%$), it is automatically placed in **Quarantine**.
2. Open the Ingestion Dashboard and select **Quarantine Queue** (`http://localhost:3000/quarantine`).
3. Select the quarantined item to inspect filename metadata, page context, and classification signals.
4. Correct any mismatched fields (AMC Name, Scheme Name, Period, Category) and click **Approve** or **Update** to publish.
