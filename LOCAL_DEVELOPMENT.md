# Local Development

This runbook covers the local setup, execution, and testing workflow for the MediaDock application.

## Prerequisites

- Node.js 20 or newer (for frontend and Firebase Emulator).
- Python 3.10 or newer (for backend).
- Firebase CLI (`npm install -g firebase-tools`).

## Local Setup

### 1. Environment Variables
Create a local environment file from the template:
```bash
cp .env.example .env
```
Populate `.env` with:
- `OMDB_API_KEY`: Your OMDb API key for backend scanner.
- `GEMINI_API_KEY`: Optional for RSS-only work; required for AI scanner modes.
- `GEMINI_MODEL`: Optional approved model override; see [docs/GEMINI_MODELS.md](docs/GEMINI_MODELS.md).
- `VITE_FIREBASE_*`: Your Firebase web project configuration.

### 2. Frontend & Emulator Setup
Install the root Node dependencies which include the frontend dependencies and rules testing packages:
```bash
npm install
```

### 3. Backend Setup
Create a virtual environment and install the backend package in editable mode:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate
pip install -e ./backend
```

## Running the Application Locally

### Frontend Development Server
Start Vite with HMR:
```bash
npm run dev
```

### Firebase Emulators
Start the Firestore and Auth emulators using a demo project ID:
```bash
firebase emulators:start --project demo-mediadock
```

### Backend Scanner (Dry Run)
The current CLI reads the configured RSS feeds and can parse them without OMDb or
Firestore writes. Do not pass a fixture path as a positional argument; an
explicit fixture option is part of the later parser/fetcher work in
`docs/BACKEND_REFACTORING_PROMPTS.md`:
```bash
python -m movies_feed.cli --config legacy/config.json --mode rss --parse-only
```

Use the Firebase emulator and synthetic fixtures for automated tests. The
scanner's `--dry-run` still permits external API calls in the current
implementation; `--parse-only` is the mode that disables OMDb for RSS parsing.

## Testing

The canonical, currently verified commands live in `docs/ai/TESTING.md`. Please refer to that document for the exact commands to run frontend tests, backend tests, rules tests, and typechecks.

Do not use live RSS, OMDb, Firebase, or deployed Pages as a substitute for unit and emulator tests.


## Troubleshooting

### Python package is missing
Confirm `python` and `pip` refer to the same virtual environment:
```bash
python -c "import sys; print(sys.executable)"
python -m pip --version
```

### Firestore permission denied
Record the path, operation, auth UID, allowlist state, and sanitized document shape. Reproduce with an emulator rules test before changing rules.

### Frontend is empty
Separate auth denial, query/index failure, empty emulator data, and UI filtering. Inspect the browser network/console output without logging tokens or credentials.

### Vite assets fail under a nested path
Use a production build/preview and verify the configured repository base path. The deployment-specific checks are in `DEPLOYMENT.md`.

## Before Opening a Pull Request
- Run every currently applicable command from `docs/ai/TESTING.md`.
- Confirm no `.env`, credential, emulator export, local data, or build output is staged.
- Ensure all CI checks pass.

For the staged backend hardening sequence, follow
`docs/BACKEND_REFACTORING_PROMPTS.md` and the model reference in
`docs/GEMINI_MODELS.md`. Do not enable production AI repair modes until the
workflow, authorization, fetch, and non-destructive repair gates are green.
