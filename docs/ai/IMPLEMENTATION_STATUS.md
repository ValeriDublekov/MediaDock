# Implementation Status

## Current Milestone

`partial` - Checkpoint F release preparation is in progress. Checkpoints A-E
are implemented; production proposal application remains disabled until the
F2-F5 operations, workflow, automated, and staging gates pass.

## Done

- `done` - Bounded RSS fetching, mode-aware CLI preflight, shared typed match
	policy, versioned OMDb cache, run-wide request budget, source-aware IDs, and
	explicit parse-log retry lifecycle are implemented.
- `done` - `ExistingTitleAuditService` audits each source/raw-title cluster,
	writes occurrence validation, and generates schema-v2 proposals with
	deterministic v3 IDs in chunks of at most 200 occurrences.
- `done` - Legacy/schema-v1 and schema-v2 `review_only` proposals coexist as
	readable, non-actionable records. Current `repair` proposals carry a typed
	target and exact source/occurrence fingerprints.
- `done` - Proposal planning is side-effect free; dry-run acquires no lease and
	performs no writes. Live Firestore application uses a per-source lease and
	one transaction for revalidation, occurrence movement, title updates, and
	final proposal status.
- `done` - Scanner `mode=all` runs RSS, audit, and reparse only. It does not
	invoke proposal application.
- `done` - Firestore rules distinguish readers from admins and CI uses explicit
	emulator project IDs and locked backend dependencies.

## Partial

- `partial` - Checkpoint F documentation and operational instructions are being
	aligned with the implemented contracts.
- `partial` - Explicit single-proposal application exists in the backend, but
	production workflow exposure remains gated by F3 and the final release checks.

## Blockers

- `blocked` - Production application cannot be enabled until the complete F4
	automated gate and F5 staging scenario pass and a verified backup/export is
	available.
- `blocked` - Production smoke checks require configured Firebase project
	identifiers and an authorized account.

## Deferred

- `deferred` - Frontend proposal review and approval UI.
- `deferred` - Automatic migration of legacy audit proposals; legacy records
	remain readable and non-actionable.
- `deferred` - Automatic or bulk proposal application.
- `deferred` - Admin control plane, full-text search, and future indexes beyond
	current query requirements.

## Current Release Gate

Complete Checkpoint F in
`docs/backend-refactoring-plan/06_CHECKPOINT_F_RELEASE.md`: operations and
recovery documentation (F2), guarded manual workflow exposure for one explicit
proposal (F3), the complete automated gate (F4), and staging plus controlled
production verification (F5).

## Update Rules

- Keep only current `done`, `partial`, `blocked`, and `deferred` facts plus the
	current release gate.
- Replace completed-step detail with milestone summaries.
- Do not duplicate Git history, test output, or architecture decisions.
- Keep this file under 100 lines.


