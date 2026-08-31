# Checkpoint C: Bounded Atomic Application

## Goal

Replace the current sequence of independent title and occurrence writes with a validated plan and one bounded Firestore transaction.

## Prerequisites

- [Checkpoint B](02_CHECKPOINT_B_PROPOSAL_CONTRACT.md) completed.
- Production proposal application remains disabled.
- Only schema-v2 `repair` proposals are actionable.

## C1: Document the Application Contract

### Scope

- `docs/ai/DATA_CONTRACTS.md`

### Work

Document before implementation:

1. schema-v2 eligibility;
2. legacy and review-only rejection;
3. source title fingerprint fields;
4. occurrence fingerprint fields;
5. exact occurrence membership requirement;
6. current policy version requirement;
7. maximum 200 occurrences per proposal;
8. lease owner and expiry fields;
9. stale and failed outcomes;
10. same-source/target behavior;
11. one-transaction catalog mutation guarantee;
12. oversized legacy proposal regeneration;
13. no partial multi-batch movement.

### Acceptance Criteria

- Every precondition and failure outcome required by C2-C7 has a documented name and persistence behavior.
- No documentation claims manual reconstruction is normal transaction recovery.

### Validation

No command. This is a documentation-only contract step.

## C2: Add a Pure Application Planner

### Scope

- `backend/src/movies_feed/proposal_application.py`
- `backend/tests/test_proposal_application.py`

### Work

1. Add immutable `ApplicationPlan`.
2. Build it from a proposal and read-only current snapshots.
3. Validate schema version and `repair` action kind.
4. Validate current policy version.
5. Validate complete canonical target.
6. Compare source title with the proposal source fingerprint.
7. Compare exact source occurrence membership.
8. Compare every named occurrence fingerprint.
9. Reject more than 200 occurrences.
10. Define deterministic same-source/target behavior.
11. Return typed stale/ineligible outcomes.
12. Make dry-run return the plan without lease acquisition or writes.

### Acceptance Criteria

- Planning is deterministic and side-effect free.
- Every stale or ineligible case has zero repository mutation.
- Existing application tests use typed proposals rather than handwritten camelCase maps.

### Validation

```powershell
python -m unittest backend.tests.test_proposal_application -v
```

## C3: Define the Atomic Store and Fake Implementation

### Scope

- Add `backend/src/movies_feed/proposal_application_store.py`.
- Add `backend/tests/test_proposal_application_store.py`.
- Edit `backend/src/movies_feed/proposal_application.py` only for the new port.

### Work

1. Define a lease result type.
2. Define an application commit result type.
3. Define store operations for acquiring a lease and atomically committing an `ApplicationPlan`.
4. Implement the Fake store using defensive copies.
5. Recheck lease owner and every plan precondition immediately before mutation.
6. Apply all in-memory mutations only after every check succeeds.
7. Add an injected failure point before commit.
8. Make repeated application idempotent.

### Acceptance Criteria

Fake tests cover:

- target absent;
- target existing;
- partial source cluster;
- last occurrence cleanup;
- stale source title;
- changed or missing occurrence;
- policy mismatch;
- wrong lease owner;
- repeated execution;
- injected failure with zero mutations;
- dry-run with zero mutations.

### Validation

```powershell
python -m unittest backend.tests.test_proposal_application_store -v
```

## C4: Implement Firestore Lease Acquisition

### Scope

- Add `backend/src/movies_feed/firestore_proposal_application_store.py`.
- Add or extend one focused Firestore application-store emulator test file.

### Work

1. Generate a random lease owner token per attempt.
2. In a transaction, allow only `approved -> applying`.
3. Persist lease owner, lease expiry, and updated timestamp.
4. Reject a second active lease for the same source title.
5. Treat an expired lease as failed/review-required with a sanitized reason.
6. Do not infer whether catalog writes happened from lease expiry.
7. Return a typed lease result without logging proposal evidence.

### Acceptance Criteria

- Only one worker acquires a proposal.
- Two proposals for one source title cannot apply concurrently.
- Stale recovery is deterministic and does not mutate catalog data.

### Validation

Run only the focused Firestore application-store emulator test through project `demo-mediadock`.

## C5: Implement One Firestore Commit Transaction

### Scope

- `backend/src/movies_feed/firestore_proposal_application_store.py`
- Focused Firestore application-store emulator tests.

### Work

Inside one Firestore transaction:

1. Read the proposal and verify `applying` plus lease owner.
2. Read source and target titles.
3. Read every named source occurrence.
4. Read source occurrence membership needed to decide source deletion.
5. Revalidate schema, policy, source fingerprint, membership, and occurrence fingerprints.
6. Merge or create the target title using established merge semantics.
7. Write target occurrences.
8. Delete only the named source occurrences.
9. Delete source title only if no occurrences remain; otherwise invalidate/recompute its aggregate validation.
10. Invalidate/recompute target aggregate validation.
11. Mark the proposal `applied` and clear its lease.
12. Keep total transaction writes below 500 under the 200-occurrence limit.

### Acceptance Criteria

- Transaction retry is safe.
- Failure before commit causes no catalog or applied-status mutation.
- No direct application write occurs outside this transaction.
- Only proposal-named occurrences move.

### Validation

Run only the focused Firestore application-store emulator test through project `demo-mediadock`.

## C6: Split Oversized Clusters Deterministically

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Sort exact occurrence IDs.
2. Split clusters into chunks of at most 200.
3. Generate v3 identity independently for each chunk.
4. Ensure chunks are stable, non-overlapping, and exhaustive.
5. Reject oversized legacy proposals in the planner; do not split them during application.

### Acceptance Criteria

- 200 occurrences produce one proposal.
- 201 occurrences produce two proposals.
- Reruns produce the same chunk boundaries and IDs.
- No proposal exceeds the transaction bound.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

## C7: Wire Application Service to the Atomic Store

### Scope

- `backend/src/movies_feed/proposal_application.py`
- `backend/src/movies_feed/scanner.py`
- `backend/src/movies_feed/cli.py`
- Focused application and CLI tests.

### Work

1. Remove direct title and occurrence mutation from `ProposalApplicationService`.
2. Build a plan.
3. Return it directly for dry-run.
4. Acquire a lease for live application.
5. Commit through the atomic store.
6. Persist only sanitized failure reason metadata.
7. Update ScanRun counters and status truthfully.
8. Keep the production feature gate disabled.
9. Remove any code path that applies all approved proposals without an explicit ID.

### Acceptance Criteria

- Service orchestration contains no multi-write catalog move.
- Incomplete, stale, legacy, review-only, or oversized proposals fail without catalog mutation.
- Applied, skipped, and failed counters match the actual outcome.

### Validation

```powershell
python -m unittest backend.tests.test_proposal_application backend.tests.test_proposal_application_store backend.tests.test_cli -v
```

## C8: Checkpoint Gate

Run each command once:

```powershell
python -m unittest discover -s backend/tests -v
```

Then run the focused Firestore application-store emulator suite once with explicit project ID `demo-mediadock`.

The checkpoint passes when:

- The complete backend suite passes.
- Fake and Firestore stores satisfy the same contract.
- Injected transaction failure leaves no partial catalog movement.
- Production application remains disabled.

Proceed to [Checkpoint D](04_CHECKPOINT_D_AUDIT_CORRECTNESS.md).
