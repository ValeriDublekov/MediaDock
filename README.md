# Media Hub Dashboard & Scanner

> **Migration status:** The current JSON/HTML implementation remains operational
> while a Firestore + React migration is prepared. Start with
> [AI_STUDIO_MIGRATION_GUIDE.md](AI_STUDIO_MIGRATION_GUIDE.md) and check
> [docs/ai/IMPLEMENTATION_STATUS.md](docs/ai/IMPLEMENTATION_STATUS.md) before
> changing the repository structure.

## Migration Documentation

- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) - current and staged local setup,
   execution, testing, and emulator workflow.
- [DEPLOYMENT.md](DEPLOYMENT.md) - target Firebase, GitHub Actions, and GitHub Pages
   deployment runbook.
- [docs/ai/PROJECT_CONTEXT.md](docs/ai/PROJECT_CONTEXT.md) - compact entry context
   for AI implementation sessions.
- [docs/ai/ARCHITECTURE.md](docs/ai/ARCHITECTURE.md) - target components, trust
   boundaries, and dependency rules.
- [docs/ai/DATA_CONTRACTS.md](docs/ai/DATA_CONTRACTS.md) - Firestore schema,
   queries, IDs, ownership, and write boundaries.
- [docs/ai/TESTING.md](docs/ai/TESTING.md) - canonical verified test commands.

## Overview

MediaDock is a personal media aggregator that scans RSS feeds, enriches titles with metadata via the OMDb API, and presents them in an interactive catalog.

The system has been migrated to a modern full-stack architecture:
- **Backend Scanner**: A Python CLI application (`backend/`) that reads RSS feeds, queries OMDb, and upserts data into Cloud Firestore. It is orchestrated via a daily GitHub Actions workflow.
- **Frontend Catalog**: A React + Vite SPA (`frontend/` or root) built with Tailwind CSS, offering realtime filtering and cursor-based pagination. It is deployed on GitHub Pages.
- **Database & Auth**: Google Cloud Firestore provides persistence, and Firebase Authentication (Google Sign-In) ensures only allowlisted users can view the catalog.

## File Structure

```text
MediaDock/
├── backend/                  # Python scanner and CLI
├── firebase/                 # Firestore rules and indexes
├── src/                      # React frontend application
├── docs/ai/                  # Compact architecture and data contracts
├── legacy/                   # Deprecated JSON/HTML implementation
├── .github/workflows/        # CI, Scanner, and Pages deployment pipelines
└── config.json               # Backend non-secret configuration
```

## Quick Links
- **Local Development**: See [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for running tests, emulator, and local builds.
- **Deployment**: See [DEPLOYMENT.md](DEPLOYMENT.md) for GitHub Actions and Pages runbooks.
- **AI Agent Docs**: Architecture and Firestore data contracts are in [docs/ai/](docs/ai/).
