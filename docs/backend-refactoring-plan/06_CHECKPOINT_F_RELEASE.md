# Checkpoint F: Documentation and Controlled Release

## Goal

Make documentation truthful, restore only explicit manual application behind operational confirmation, and run one complete automated and staging release gate.

## Prerequisites

- Checkpoints [A](01_CHECKPOINT_A_ISOLATE_AND_DISABLE.md), [B](02_CHECKPOINT_B_PROPOSAL_CONTRACT.md), [C](03_CHECKPOINT_C_ATOMIC_APPLICATION.md), [D](04_CHECKPOINT_D_AUDIT_CORRECTNESS.md), and [E](05_CHECKPOINT_E_RULES_AND_CI.md) passed.
- A Firestore backup/export procedure is available before production enablement.

## F1: Update Architecture, Contracts, and Status

### Scope

- `docs/ai/ARCHITECTURE.md`
- `docs/ai/DATA_CONTRACTS.md`
- `docs/ai/TESTING.md`
- `docs/ai/IMPLEMENTATION_STATUS.md`
- `docs/BACKEND_PARSING_PIPELINES.md`

### Work

1. Describe `ExistingTitleAuditService` ownership.
2. Describe proposal schema v2 and ID v3.
3. Describe legacy proposal coexistence and non-actionability.
4. Describe review-only versus repair proposals.
5. Describe the 200-occurrence bound.
6. Describe lease and single-transaction guarantees.
7. State that `mode=all` is non-destructive.
8. Replace status prose with `done`, `partial`, `blocked`, and `deferred` facts.
9. Remove the nonexistent Prompt 11 reference.
10. Remove or update obsolete risk statements.
11. Keep frontend approval UI and automatic legacy migration explicitly deferred.

### Acceptance Criteria

- Documents agree on field names, statuses, limits, and operational behavior.
- No document claims bulk or automatic proposal application is safe or supported.
- Implementation status names the current release gate rather than a nonexistent prompt.

### Validation

No command. This is a documentation-only step.

## F2: Update Operations and Recovery Instructions

### Scope

- `DEPLOYMENT.md`
- `LOCAL_DEVELOPMENT.md`
- `scripts/run_scanner.ps1` only if help text is stale.
- `scripts/run_scanner.sh` only if help text is stale.

### Work

1. Document required backup/export before production application.
2. Document explicit proposal ID and dry-run first.
3. Document the manual production application safeguards.
4. Document backup confirmation.
5. Document stale/failed proposal review flow.
6. Document the 200-occurrence bound and regeneration behavior.
7. Replace partial-write/manual-reconstruction language with transaction rollback semantics.
8. Ensure every command matches the final CLI.

### Acceptance Criteria

- Operators cannot mistake `all` for an apply mode.
- Recovery instructions match actual transactional behavior.
- Local scripts do not advertise unsupported bulk application.

### Validation

```powershell
python -m unittest backend.tests.test_cli -v
```

## F3: Re-enable Explicit Manual Production Application

### Scope

- `.github/workflows/scanner.yml`
- `backend/src/movies_feed/cli.py`
- `backend/tests/test_workflow_security.py`
- `backend/tests/test_cli.py`

### Work

1. Restore `apply-proposals` only as an explicit manual workflow mode.
2. Require exactly one proposal ID.
3. Require an explicit backup-confirmation input with one exact accepted value.
4. Pass all inputs through environment variables and validate before command construction.
5. Keep shell-array argument passing.
6. Keep application absent from schedules.
7. Keep application absent from `mode=all`.
8. Do not support applying every approved proposal.
9. Prevent same-run proposal generation and application.

### Acceptance Criteria

- Workflow fails closed without proposal ID or backup confirmation.
- Invalid inputs cannot reach executable shell source.
- Only one previously approved proposal can be applied per dispatch.
- Dry-run remains available without enabling production mutation.

### Validation

```powershell
python -m unittest backend.tests.test_cli backend.tests.test_workflow_security -v
```

## F4: Final Automated Gate

Run each command once in a complete toolchain environment:

1. Full backend suite:

```powershell
python -m unittest discover -s backend/tests -v
```

2. Focused Firestore proposal application emulator suite with project `demo-mediadock`.
3. Firestore Rules emulator suite with project `demo-mediadock`.
4. Frontend unit suite.
5. Frontend typecheck:

```powershell
npx tsc --noEmit
```

6. Frontend production build:

```powershell
npm run build
```

7. Dependency integrity:

```powershell
python -m pip check
```

### Acceptance Criteria

- All commands pass.
- No production test performs live RSS, OMDb, Gemini, or Firestore calls.
- Dry-run tests prove zero mutation.
- Incomplete application makes ScanRun and process result non-successful.
- Workflow static validation covers every active workflow.

Do not enable production application if any gate is skipped or red.

## F5: Final Staging and Production Gate

### Staging Scenario

Use emulator or non-production Firestore data:

1. Seed one source title with at least two occurrence clusters.
2. Generate one repair proposal through the real audit service.
3. Rerun audit and confirm the same proposal ID and preserved status.
4. Approve the proposal through the supported operator path.
5. Run dry-run and record the exact plan.
6. Apply the proposal.
7. Verify only named occurrences moved.
8. Verify source title retention or deletion is correct.
9. Verify target title merge and aggregate validation state.
10. Verify proposal is `applied` and lease is cleared.
11. Run apply again and verify idempotent skip.
12. Verify ScanRun counters and process exit status.

### Production Enablement

1. Create and verify a backup/export.
2. Select one reviewed proposal ID.
3. Confirm it is schema v2, ID v3, `repair`, approved, current-policy, and within 200 occurrences.
4. Run production dry-run.
5. Compare the plan with the approved evidence.
6. Apply that one proposal.
7. Verify catalog and proposal state.

### Final Acceptance Criteria

- Staging scenario passes end to end with the real producer object.
- First production application is bounded to one reviewed proposal.
- A current backup exists.
- There is no automatic or bulk production apply path.

After F5, update [`README.md`](README.md) quality assessment only if implementation revealed a missing prerequisite or invalid assumption.
