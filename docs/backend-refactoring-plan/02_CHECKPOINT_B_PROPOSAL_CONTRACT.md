# Checkpoint B: Proposal Contract

## Goal

Replace ad hoc proposal dictionaries with one typed, versioned contract; eliminate cross-feed identity collisions; preserve operator decisions during audit reruns; and make AI validation consistently fail closed.

## Prerequisites

- [Checkpoint A](01_CHECKPOINT_A_ISOLATE_AND_DISABLE.md) passed.
- Proposal application remains disabled.
- Follow the command budget in [`README.md`](README.md).

## B1: Extract Proposal Domain Code Mechanically

### Scope

- Add `backend/src/movies_feed/audit_proposal.py`.
- Edit `backend/src/movies_feed/models.py` and directly affected imports.
- Edit `backend/tests/test_audit_proposal.py` only for imports.

### Work

Move these existing symbols without behavior changes:

- `AuditProposal`
- proposal status types and constants
- status transition validation
- secret redaction helpers
- evidence-size validation
- proposal deserialization

Use temporary re-exports only when needed for compatibility.

### Acceptance Criteria

- Serialized keys and values remain identical.
- Existing proposal tests require no assertion changes.
- No new schema fields are introduced yet.

### Validation

```powershell
python -m unittest backend.tests.test_audit_proposal -v
```

## B2: Add Typed Metadata Value Objects

### Scope

- `backend/src/movies_feed/audit_proposal.py`
- `backend/tests/test_audit_proposal.py`

### Work

1. Add immutable `ProposalSourceSnapshot`.
2. Add immutable `ProposalTarget`.
3. Use snake_case attributes in Python and camelCase only in Firestore dictionaries.
4. Validate non-empty titles.
5. Validate optional IMDb IDs with the existing project format.
6. Restrict source media type to `movie` or `series`.
7. Validate year bounds consistently with current metadata policy.
8. Preserve optional content kind and broadcast range without changing source type semantics.

### Acceptance Criteria

- Invalid or partial target objects cannot be constructed.
- Both value objects have round-trip tests.
- No consumer reads raw metadata map keys after migration is complete.

### Validation

```powershell
python -m unittest backend.tests.test_audit_proposal -v
```

## B3: Add Proposal Schema Version and Action Kind

### Scope

- `backend/src/movies_feed/audit_proposal.py`
- `backend/tests/test_audit_proposal.py`

### Work

1. Add `schema_version`, serialized as `schemaVersion`.
2. Add `action_kind`, serialized as `actionKind`.
3. Support exactly `review_only` and `repair`.
4. Require a complete `ProposalTarget` for `repair`.
5. Forbid an actionable target for `review_only`.
6. Read missing schema version as legacy version 1.
7. Read legacy proposals as non-actionable review-only documents.
8. Never infer missing target fields from legacy dictionaries.

### Acceptance Criteria

- New repair proposals are schema version 2.
- Legacy documents remain readable.
- Legacy documents cannot pass application eligibility.
- Current and legacy round trips are covered.

### Validation

```powershell
python -m unittest backend.tests.test_audit_proposal -v
```

## B4: Return Canonical Candidate Data

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Replace the suggestion inspection dictionary with a small typed outcome.
2. For accepted candidates, retain canonical `OmdbMovieResult` data:
   - IMDb ID
   - resolved title
   - canonical year
   - source media type
   - content kind
   - broadcast range
3. Do not produce a target for not-found, retryable, malformed, excluded, rejected, or ambiguous outcomes.
4. Keep existing counters and needs-review logging unchanged.

### Acceptance Criteria

- Valid suggestions retain the OMDb IMDb ID.
- Uncertain outcomes carry no actionable target.
- No catalog mutation is added.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

## B5: Generate Only Typed Proposals

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Build `ProposalSourceSnapshot` from the stored title.
2. Build `ProposalTarget` only from B4's complete accepted candidate.
3. Emit `repair` only when a complete target exists.
4. Emit `review_only` for every other mismatch or ambiguity.
5. Remove ad hoc `current_metadata` and `proposed_metadata` construction from the audit service.
6. Convert A1's integration regression into a normal passing test.

### Acceptance Criteria

- The exact scanner-generated proposal can be consumed without key conversion or guessing.
- The target ID uses canonical media type and IMDb ID.
- Review-only proposals cannot enter the repair path.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

## B6: Add Proposal ID v3

### Scope

- `backend/src/movies_feed/ids.py`
- `backend/tests/test_audit_proposal.py`

### Work

Create a new ID helper whose canonical input contains:

1. version marker `v3`;
2. source title ID;
3. stable source feed ID;
4. normalized raw title;
5. sorted exact occurrence IDs;
6. policy version.

Keep old helpers for reading/coexistence. Only new writes will use v3 after B7.

### Acceptance Criteria

- Input occurrence order does not change the ID.
- Different feed IDs produce different IDs.
- Different occurrence membership produces different IDs.
- Different policy versions produce different IDs.
- Empty required identity fields fail.

### Validation

```powershell
python -m unittest backend.tests.test_audit_proposal -v
```

## B7: Use v3 IDs During Audit Generation

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Pass stable source feed ID, normalized raw title, and exact occurrence IDs to B6's helper.
2. Keep cluster occurrence IDs sorted before identity generation.
3. Add a two-feed same-raw-title regression.
4. Add an unchanged-rerun identity test.
5. Add a changed-membership revision test.

### Acceptance Criteria

- Cross-feed clusters never overwrite one another.
- An unchanged rerun addresses the same proposal.
- Changed cluster membership creates a new proposal revision.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

## B8: Add Status-Preserving Audit Refresh

### Scope

- `backend/src/movies_feed/repository.py`
- `backend/src/movies_feed/firestore_repository.py`
- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_audit_proposal.py`
- `backend/tests/test_firestore_repository.py`

### Work

1. Add a repository operation specifically for audit refresh.
2. Do not route refresh through a fresh `pending` status transition.
3. Preserve `createdAt` for all existing proposals.
4. Refresh evidence and timestamps only while status is `pending`.
5. Preserve status, lease, and operator-visible data for `approved`, `applying`, `applied`, and `rejected`.
6. Use the new v3 ID for changed revisions rather than resetting an existing proposal.
7. Keep Fake and Firestore behavior identical.

### Acceptance Criteria

- Audit reruns do not throw forbidden transition errors.
- Audit reruns do not erase approvals, rejections, applied status, or leases.
- New evidence cannot mutate a terminal decision in place.

### Validation

```powershell
python -m unittest backend.tests.test_audit_proposal backend.tests.test_firestore_repository -v
```

## B9: Remove the Weaker AI Validation Path

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/src/movies_feed/ai_validator.py`
- `backend/tests/test_existing_title_audit.py`
- Existing AI matcher tests only if directly affected.

### Work

1. Remove the local permissive recheck-result validator.
2. Consume only output from `validate_batch_recheck_results` or its typed equivalent.
3. Require confidence for every item.
4. Use only the central audit confidence threshold.
5. Update injected matcher doubles to return complete contract-compliant results.
6. Keep missing, duplicate, extra, low-confidence, and malformed output fail-closed.

### Acceptance Criteria

- Missing confidence fails in every matcher path.
- There is one authoritative audit result validator.
- Incomplete batches remain non-destructive and make the run non-successful.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit backend.tests.test_ai_matcher -v
```

## B10: Checkpoint Review

Do not run the full backend suite here. A5 established the baseline, and each B step ran its owning focused tests.

Confirm by inspection only:

- Audit production code no longer uses proposal metadata dictionaries.
- New writes use schema version 2 and ID v3.
- Legacy proposals are non-actionable.
- Operator status survives reruns.
- Application remains disabled.

Proceed to [Checkpoint C](03_CHECKPOINT_C_ATOMIC_APPLICATION.md).
