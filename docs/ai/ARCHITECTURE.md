# Architecture

## Status

This describes the implemented architecture at the Checkpoint F release gate.
The remaining release work is tracked in
`docs/backend-refactoring-plan/06_CHECKPOINT_F_RELEASE.md`.

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

`match_policy.py` is the shared domain policy boundary for source type,
content kind, broadcast ranges, year semantics, exclusions, and typed
accepted/rejected/ambiguous decisions. OMDb normalization supplies its input;
scanner modes do not duplicate those deterministic checks.

`ExistingTitleAuditService` owns existing-title audit orchestration. It groups
occurrences by source feed and raw title, evaluates deterministic and AI
evidence, writes occurrence-level validation for valid clusters, records
review outcomes, and produces bounded audit proposals for mismatches. It does
not move occurrences, delete titles, approve proposals, or apply proposals.
`ScannerService` supplies its repositories and callbacks and invokes it for
`recheck-existing`; proposal application is a separate
`ProposalApplicationService` path.

RSS catalog ordering uses a separate read model. During a feed scan,
`ScannerService` records accepted title IDs with their configured feed and
original entry positions. After the RSS phase completes successfully for every
feed, `FirestoreRssSnapshotRepository` stages an immutable generation under
`rssSnapshots/{snapshotId}/items` and atomically updates
`rssSnapshotState/current`. Partial or failed runs leave the previous generation
visible. The snapshot groups movies before series and deduplicates a title at
its first RSS position; it does not change `firstSeenAt`, `lastSeenAt`, or
historical occurrences.

Current audit producers write proposal schema v2 with deterministic v3 IDs.
A v3 ID covers the source title, source feed, normalized raw title, sorted
occurrence IDs, and policy version. `review_only` proposals preserve evidence
but cannot mutate the catalog. `repair` proposals additionally contain a typed
target plus exact source-title and occurrence fingerprints. Each proposal is
limited to 200 occurrences; larger clusters are emitted as multiple bounded
proposals.

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

The initial `Latest` mode reads the current RSS snapshot pointer, pages its
ordered title references, hydrates `titles/{titleId}` documents in chunks, and
keeps the reference order after hydration. The historical `Catalog` mode keeps
the date-ordered title query. Favorites and hidden titles remain keyed by title
ID, and title cards continue to load all historical occurrences.

### Firebase

- Firebase Authentication provides Google Sign-In.
- Firestore stores catalog, occurrences, cache, scan runs, and access documents.
- Firestore stores immutable RSS snapshot generations and a backend-only current
        snapshot pointer for the Latest catalog mode.
- Security rules authorize browser operations.
- Firebase Admin SDK bypasses client rules and is restricted to GitHub Actions.
- Emulator Suite provides local integration and rules testing.

## Trust Boundaries

| Actor | Allowed operations |
| --- | --- |
| Anonymous browser | Authentication flow only; no Firestore data access |
| Authenticated non-allowlisted user | No catalog access |
| Allowlisted reader | Read catalog, parse logs, and settings; write only own user preferences |
| Allowlisted admin | Reader access plus validated manual-mapping writes; scanner settings remain server-managed |
| Future owner client | Validated CRUD only in own `users/{uid}` namespace |
| Scanner service account | Catalog/cache/scan writes through Admin SDK |

Do not introduce blanket authenticated writes. Manual-mapping administration
uses the explicit `allowlist/{uid}.role == "admin"` document field and a
dedicated validated path. Scanner settings are read-only in the browser until
a server-side control plane is available. A missing role remains a
backward-compatible reader, while unknown roles are denied access.

## Deployment Topology

```text
RSS feeds ----> GitHub Actions daily scanner ----> Firestore
                        |                              ^
                        `----> OMDb API/cache          |
                                                       |
User browser <---- GitHub Pages React app ---- Firebase Auth/rules
```

The scanner writes a new snapshot generation before promoting the pointer. The
browser never reads a generation by time or `lastSeenAt`; it follows the
pointer, so an incomplete run cannot reorder the Latest view.

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
        produce a non-success process result when the phase is incomplete. One
        resolver budget counts actual OMDb HTTP attempts across all scanner
        phases; a quota response stops further OMDb requests for the run.
- Existing-title audit mismatches and uncertain evidence are persisted as
        `needs_review` outcomes and audit proposals; the audit phase does not
        delete titles or move occurrences.
- Legacy schema-v1 proposals remain readable but are non-actionable. They are
        not automatically migrated or reconstructed into repair proposals.
- Live application is limited to one explicit, approved, current-policy,
        schema-v2 `repair` proposal. A per-source lease serializes attempts, and
        the Firestore commit rechecks the lease, proposal, fingerprints, and
        membership before moving at most 200 named occurrences in one
        transaction. A failed transaction commits no partial catalog move.
- Dry-run planning does not acquire a lease or write. Scanner `mode=all` runs
        RSS, audit, and reparse phases only; it never applies proposals.
- Scan runs record bounded error summaries without secrets.
- Repository writes are idempotent so a workflow rerun is safe.
- Snapshot generations are staged before pointer promotion. A partial or failed
        RSS phase cannot replace the last complete Latest view.
- Frontend exposes loading, empty, denied, retryable error, and end states.

## Deferred Architecture

- Full-text search service.
- Client write feature and admin editor; any future privileged control plane must
        use an explicit admin role and server-side credential boundary.
- Cloud-hosted scanner outside GitHub Actions.
- Notifications and user preference features.
- Automated legacy JSON data migrations.
- Frontend review UI for audit proposals.
- Automatic migration of legacy audit proposals.
- Automatic or bulk proposal application.
- Firestore indexes for future multi-field combinations beyond current query demands.
- Historical backfill of RSS snapshot generations; the first successful RSS run
        after deployment establishes the initial Latest snapshot.
