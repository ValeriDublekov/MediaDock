# Architecture

## Status

This describes the target architecture. Bootstrap (P00/M0), the MVP wiring,
workflow/client hardening, and the bounded RSS boundary from Prompts 0A-0C are
present. The remaining refactoring work is tracked in
`docs/BACKEND_REFACTORING_PROMPTS.md`.

## Components

### Backend

The Python backend uses inward-facing domain/application code and outward-facing
adapters:

```text
CLI / GitHub Actions
        |
Scanner application service
        |
Domain models and policy/resolver interfaces
        |             |                |
FeedFetcher  OMDb/AI adapters  Firestore Admin adapters
```

Business logic must not initialize Firebase, read process arguments, or perform
HTTP requests directly. Tests replace outbound adapters with fakes.

`FeedFetcher` owns the code-defined HTTPS host allowlist, public DNS and
redirect validation, TLS transport, response/entry bounds, and explicit local
fixture reads. `ScannerService` receives feed bytes from that adapter and is the
only active caller of `feedparser`.

### Frontend

```text
React views and components
        |
Catalog/auth application layer
        |
Typed repository interfaces
        |
Firebase client adapters
```

Components do not import Firestore query functions. This keeps queries testable
and permits later user-data write adapters without coupling presentation code.

### Firebase

- Firebase Authentication provides Google Sign-In.
- Firestore stores catalog, occurrences, cache, scan runs, and access documents.
- Security rules authorize browser operations.
- Firebase Admin SDK bypasses client rules and is restricted to GitHub Actions.
- Emulator Suite provides local integration and rules testing.

## Trust Boundaries

| Actor | Allowed operations |
| --- | --- |
| Anonymous browser | Authentication flow only; no Firestore data access |
| Authenticated non-allowlisted user | No catalog access |
| Allowlisted reader | Read catalog, parse logs, and settings; write only own user preferences |
| Allowlisted admin | Reader access plus validated scanner-settings and manual-mapping writes |
| Future owner client | Validated CRUD only in own `users/{uid}` namespace |
| Scanner service account | Catalog/cache/scan writes through Admin SDK |

Do not introduce blanket authenticated writes. Admin editing uses the explicit
`allowlist/{uid}.role == "admin"` document field, dedicated validated paths, and
rules tests; it does not reuse owner-data permissions. A missing role remains a
backward-compatible reader, while unknown roles are denied access.

## Deployment Topology

```text
RSS feeds ----> GitHub Actions daily scanner ----> Firestore
                        |                              ^
                        `----> OMDb API/cache          |
                                                       |
User browser <---- GitHub Pages React app ---- Firebase Auth/rules
```

The frontend is a GitHub Pages project site, so Vite asset paths must use the
repository base path. Firebase Authorized Domains must include the Pages host.

## Dependency Rules

- Domain models depend on no Firebase, HTTP, CLI, or React implementation.
- Application services depend on interfaces, not concrete external clients.
- Adapters may depend on SDKs and convert external data at their boundary.
- Workflows invoke documented commands; they do not duplicate business logic.
- Operational docs refer to `docs/ai/TESTING.md` for canonical test commands.
- Contract changes update the owning AI doc in the same commit.

## Runtime Configuration

### Secret server values

- `OMDB_API_KEY`
- `GEMINI_API_KEY` (optional, for AI title extraction and OMDb validation)
- `GEMINI_MODEL` (optional stable or explicitly approved preview model; see [`GEMINI_MODELS.md`](../GEMINI_MODELS.md))
- Firebase Admin credentials

These exist in local ignored environment/credential storage or GitHub Secrets.

### Public frontend values

- Firebase API key
- Auth domain
- Project ID
- Storage/app/messaging identifiers when required
- GitHub repository owner, repository, and workflow filename for the protected
        Actions link

The browser has no OMDb key, GitHub PAT, Firebase Admin credential, or scanner
control token. Manual dispatch takes place in GitHub's authenticated Actions UI;
manual title correction writes an admin-protected mapping for the scanner.

Public Firebase configuration is built through `VITE_` variables. Authorization
still depends on Authentication and Firestore rules.

## Failure Strategy

- A malformed feed item does not abort the entire scan.
- Untrusted feed URLs are rejected by a code-owned, bounded fetch adapter before
        feed parsing.
- OMDb and AI limit/error states are explicit, included in scan counters, and
        produce a non-success process result when the phase is incomplete.
- Scan runs record bounded error summaries without secrets.
- Repository writes are idempotent so a workflow rerun is safe.
- Frontend exposes loading, empty, denied, retryable error, and end states.

## Deferred Architecture

- Full-text search service.
- Client write feature and admin editor; any future privileged control plane must
        use an explicit admin role and server-side credential boundary.
- Cloud-hosted scanner outside GitHub Actions.
- Notifications and user preference features.
