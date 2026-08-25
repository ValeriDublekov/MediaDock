# MoviesFeed Project Context

## Purpose

MoviesFeed aggregates torrent RSS feeds, parses media titles, enriches new titles
with OMDb metadata, and presents an authenticated searchable catalog.

## Current State

- The legacy Python scanner and config are isolated under `legacy/`.
- Local JSON files stored scan history, catalog data, and OMDb cache in the legacy scanner.
- Parser tests use Atom fixtures under `tests/fixtures/`.
- `docs/BACKEND_REFACTORING_PROMPTS.md` defines the current incremental hardening roadmap.
- The repository has completed bootstrap prompt P00 (Milestone M0).

## Target State

- `legacy/`: sanitized read-only reference implementation.
- `backend/`: scheduled Python scanner and tests.
- `frontend/`: React, Vite, TypeScript, and Firebase client SDK.
- `firebase/`: Firestore rules, indexes, and emulator configuration.
- `.github/workflows/`: CI, daily scanner, and GitHub Pages deployment.
- `docs/ai/`: compact context for coding agents.

## Primary Flow

1. GitHub Actions starts the scanner daily or by manual dispatch.
2. The scanner reads configured RSS/Atom feeds.
3. The parser extracts title, year, media type, quality, and rip type.
4. The scanner reuses valid Firestore OMDb cache data or calls OMDb.
5. Filters reject configured countries and genres.
6. Repositories idempotently upsert titles and torrent occurrences.
7. An authenticated allowlisted user reads paginated catalog data in React.

## Product Behavior to Preserve

- Separate movie and series feed hints.
- Title/year parsing from RuTracker-style feed titles.
- OMDb title+year lookup with title-only fallback.
- Country and genre exclusion filters.
- Movie, series, documentary, and short display types.
- Search, country/type filters, rating thresholds, vote threshold, and links.
- Parse-only diagnostics that make no OMDb calls.

## Boundaries

- GitHub Pages hosts static frontend assets only.
- GitHub Actions runs Python and writes server-managed Firestore data.
- The target browser boundary excludes OMDb and Firebase Admin credentials; the current client-secret exposure is an open hardening item in Prompt 0B.
- UI components access data through typed repositories, not direct Firestore queries.
- MVP has no client write feature, but owner-scoped writes are a supported extension.
- Firestore is the catalog source of truth; generated HTML and local JSON are legacy.
- Optional `GEMINI_API_KEY` enables AI batch parsing and OMDb verification. Current prompts are inline in `ai_matcher.py`; the standalone prompt files are not yet the runtime source of truth.
- `GEMINI_MODEL` selects an approved model from [`GEMINI_MODELS.md`](../GEMINI_MODELS.md), subject to runtime capability validation.

## Stable Vocabulary

- **Title:** normalized movie or series metadata, usually identified by IMDb ID.
- **Occurrence:** one torrent/feed appearance associated with a title.
- **Scan run:** one scanner execution and its counters/status.
- **Allowlisted user:** authenticated user authorized to access the catalog.
- **Server-managed:** writable only through trusted Firebase Admin credentials.
- **Owner-scoped:** future client data under a user's UID with strict rules.

## Context Rules

- Read this file for every implementation prompt.
- Add only the one or two specialized AI docs relevant to the task.
- Read legacy files only when a prompt names the behavior being preserved.
- Never attach real `.env`, service-account, catalog data, build output, or logs.
- Update this file only when stable purpose, boundaries, or primary flow changes.
