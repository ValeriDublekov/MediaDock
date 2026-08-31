# Checkpoint D: Audit Correctness

## Goal

Invalidate stale occurrence validation when match-relevant data changes and apply `audit_days` to occurrence clusters rather than aggregate title timestamps.

## Prerequisites

- [Checkpoint C](03_CHECKPOINT_C_ATOMIC_APPLICATION.md) passed.
- Follow the command budget in [`README.md`](README.md).

## D1: Add Validation Invalidation Characterization Tests

### Scope

- `backend/tests/test_repository.py`
- `backend/tests/test_existing_title_audit.py`
- Do not edit production code.

### Work

Add cases for an existing occurrence ID receiving:

1. only a newer observation timestamp;
2. a changed raw title;
3. a changed source feed ID or source feed type;
4. a changed source year/context used by match policy;
5. a changed target identity association.

Assert that observation-only updates should preserve validation, while every match-relevant change should clear occurrence validation and title aggregate validation.

### Acceptance Criteria

- The observation-only characterization passes.
- The match-relevant cases fail specifically because current merge behavior preserves stale validation.
- No production code changes are included.

### Validation

```powershell
python -m unittest backend.tests.test_repository backend.tests.test_existing_title_audit -v
```

D1 intentionally introduces focused failing regressions. Record them and continue only if they demonstrate stale validation preservation.

## D2: Implement a Validation Fingerprint

### Scope

- `backend/src/movies_feed/repository.py`
- `backend/src/movies_feed/scanner.py`
- `backend/tests/test_repository.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Add one deterministic helper for match-relevant occurrence identity.
2. Include only fields that can change match-policy or audit meaning.
3. Exclude observation timestamps and mutable display-only feed names.
4. During occurrence merge, compare existing and incoming fingerprints.
5. If the fingerprint changes, clear validation status, policy version, reason, and validation timestamp.
6. In scanner staging, clear `Title.ai_validated` and `ai_checked_at` when the merged occurrence lost validation.
7. Preserve validation for timestamp-only rescans.

### Acceptance Criteria

- Every D1 regression passes.
- Timestamp-only rescans remain idempotent.
- A meaningful change causes the title to become audit-eligible.

### Validation

```powershell
python -m unittest backend.tests.test_repository backend.tests.test_existing_title_audit backend.tests.test_scanner -v
```

## D3: Add Cluster-Level Recency Tests

### Scope

- `backend/tests/test_existing_title_audit.py`
- Do not edit production code.

### Work

Add cases for:

1. one old and one recent cluster under the same title;
2. a recent occurrence under a title with a stale aggregate timestamp;
3. an old occurrence under a title with a recent aggregate timestamp;
4. unlimited `audit_days=0`;
5. an orphan title.

Use occurrence `last_seen_at` as the controlling observation timestamp.

### Acceptance Criteria

- Tests prove that title-level timestamp filtering is incorrect.
- Expected AI batch IDs and counters are explicit.
- Orphan behavior is specified independently of cluster recency.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

D3 intentionally leaves the new recency regressions failing until D4.

## D4: Apply audit_days at Cluster Level

### Scope

- `backend/src/movies_feed/existing_title_audit.py`
- `backend/tests/test_existing_title_audit.py`

### Work

1. Remove aggregate title timestamp exclusion.
2. Load occurrences and form source/raw-title clusters first.
3. Derive each cluster's observation recency from occurrence `last_seen_at`.
4. Keep only clusters within the cutoff when `audit_days > 0`.
5. Include every cluster when `audit_days == 0`.
6. Keep orphan handling explicit.
7. Count titles and clusters according to documented eligible/checked semantics.
8. Ensure only eligible clusters are sent to AI.

### Acceptance Criteria

- All D3 tests pass.
- A recent title timestamp cannot pull an old cluster into audit.
- A stale title timestamp cannot exclude a recent cluster.
- No publication timestamp controls audit eligibility.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

Do not run the full backend suite at this checkpoint. Proceed to [Checkpoint E](05_CHECKPOINT_E_RULES_AND_CI.md).
