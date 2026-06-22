# Nivesh AI Ingestion Pipeline

A resilient, multi-stage data discovery, acquisition, classification, and extraction system targeting heterogeneous Asset Management Company (AMC) disclosures.

## Project Architecture

This application consists of three main components orchestrating the SEBI-mandated portfolio disclosures:
- **FastAPI Pipeline Server** (`/pipeline`): Responsible for crawling via Playwright, identity resolution matching SEBI taxonomy schemes, PDF/Excel table extraction, drift monitoring, and multi-layer novelty validation.
- **Next.js Dashboard** (`/dashboard`): An analytics interface using React, TailwindCSS, and custom premium layouts to handle manual quarantine review flows and monitor runs.
- **PostgreSQL Database**: Dynamic logging and warehouse schemas.

## Quick Start

Execute from the root directory:
```bash
docker-compose up -d --build
```
- API Server: `http://localhost:8000/docs`
- Ingestion Dashboard: `http://localhost:3000`

For further operations and execution setups, refer to the [System Runbook](docs/runbook.md).
