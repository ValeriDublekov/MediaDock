# Local Development

This runbook covers the current legacy project and the target React/Firebase
application. Commands marked **target** become available only after the referenced
migration prompt in `AI_STUDIO_MIGRATION_GUIDE.md` is complete.

## Current Repository Status

The repository is currently before P00:

- Python scanner and tests are at repository root.
- React, Firestore Emulator, and target backend packages do not exist yet.
- Do not invent target commands before their package manifests are committed.
- See `docs/ai/IMPLEMENTATION_STATUS.md` for the exact next prompt.

## Prerequisites

Current legacy work:

- Python 3.10 or newer.
- A virtual environment is recommended.

Target application:

- Python version selected by the backend project metadata.
- Node.js active LTS selected by the frontend project metadata.
- Java runtime supported by the Firebase Emulator Suite.
- Firebase CLI installed through the method pinned by the project.

After scaffolding, package metadata and `docs/ai/TESTING.md` are authoritative for
versions and commands.

## Current Legacy Setup

From repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

If script execution policy prevents activation, invoke `.venv\Scripts\python.exe`
directly instead of changing machine-wide policy.

The current scanner expects legacy configuration. Do not run a live scan until the
exposed OMDb key has been rotated and configuration has been sanitized in P00.

## Environment Files

After P00, create local files from committed examples:

```powershell
Copy-Item .env.example .env
```

Rules:

- `.env` and service-account files are ignored and never committed.
- `OMDB_API_KEY` is backend-only.
- Firebase Admin credentials are backend-only.
- `VITE_*` Firebase web values are public client configuration, not Admin secrets.
- Prefer Firebase Emulator credentials/project IDs for local work.

Do not store JSON credentials inside a multiline `.env` value unless the backend
and deployment runbook explicitly standardize and test that representation.

## Target Local Workflow

The exact commands are added to `docs/ai/TESTING.md` when P02, P08, and P09 create
the corresponding projects. The expected order is:

1. Install backend dependencies.
2. Install frontend/rules-test dependencies.
3. Start Firestore and Auth emulators using a demo project ID.
4. Run backend repository/rules tests against emulators.
5. Start the backend fixture dry-run when scanner work is under test.
6. Start the Vite development server.

Never point automated local tests at the production Firebase project.

## Running the Legacy Scanner Safely

Available modes before migration:

```powershell
python movie_scanner.py --test-parser
python movie_scanner.py --parse-only tests/fixtures/movies_feed.atom
```

`--test-parser` and fixture-based `--parse-only` avoid OMDb calls. A normal scanner
run performs network calls and writes local data, so it is not the default test.

After P00, run these commands from the documented `legacy/` location.

## Tests

The canonical, currently verified commands live in `docs/ai/TESTING.md`.

At each migration stage, prefer this order:

1. Focused test for the changed behavior.
2. Complete package test suite.
3. Typecheck/lint where configured.
4. Production build for frontend changes.
5. Emulator integration/rules tests for Firestore changes.

Do not use live RSS, OMDb, Firebase, or deployed Pages as a substitute for unit and
emulator tests.

## Emulator Data

When emulator support is implemented:

- Use a non-production demo project ID.
- Keep exported emulator state in an ignored directory.
- Start from clean state for rules/idempotency tests.
- Use explicit import/export only for manual UI sessions.
- Stop emulators with `Ctrl+C`; do not kill unrelated Java/Node processes.

If an emulator test unexpectedly reaches production, stop immediately and inspect
project IDs and environment loading before rerunning.

## Troubleshooting

### Python package is missing

Confirm `python` and `pip` refer to the same virtual environment:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip --version
```

### Parser output changed

Run the focused fixture test, compare the raw fixture title, and avoid updating
expected values unless the parsing contract intentionally changed.

### Firestore permission denied

Record the path, operation, auth UID, allowlist state, and sanitized document shape.
Reproduce with an emulator rules test before changing rules.

### Frontend is empty

Separate auth denial, query/index failure, empty emulator data, and UI filtering.
Inspect the browser network/console output without logging tokens or credentials.

### Vite assets fail under a nested path

Use a production build/preview and verify the configured repository base path. The
deployment-specific checks are in `DEPLOYMENT.md`.

## Before Opening a Pull Request

- Run every currently applicable command from `docs/ai/TESTING.md`.
- Confirm no `.env`, credential, emulator export, local data, or build output is staged.
- Update an AI doc only when its owned contract or command changed.
- Update `IMPLEMENTATION_STATUS.md` with one next prompt, not a work diary.
