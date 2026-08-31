# Checkpoint A: Isolate and Disable

## Goal

Capture the broken producer/consumer behavior, extract the oversized audit workflow without changing behavior, and make destructive proposal application unreachable in production while remediation is in progress.

## Prerequisites

- Read [`README.md`](README.md), especially Mandatory Execution Rules.
- The findings in [`../BACKEND_REFACTORING_REVIEW_2026-08-31.md`](../BACKEND_REFACTORING_REVIEW_2026-08-31.md) are accepted.

## A1: Add Producer/Consumer Characterization Tests

### Scope

- Add `backend/tests/test_existing_title_audit.py`.
- Read existing test helpers from `backend/tests/test_scanner.py` and `backend/tests/test_proposal_application.py` only as needed.
- Do not edit production code.

### Work

1. Build the smallest fake-repository scanner setup that produces an audit mismatch proposal.
2. Use the actual proposal object produced by the scanner.
3. Approve that object through the repository contract.
4. Pass that exact object to the current `ProposalApplicationService`.
5. Assert the expected canonical target ID and target metadata.
6. Add one passing characterization proving that mismatch generation itself does not mutate titles or occurrences.

### Acceptance Criteria

- The integration regression fails because producer metadata uses a contract incompatible with the application consumer.
- It does not fail because of missing fixture data, unavailable APIs, or an incorrectly approved status.
- The non-destructive audit characterization passes.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit -v
```

A1 intentionally leaves one regression failing. Record its exact assertion and continue only if it proves the known contract mismatch.

## A2: Extract ExistingTitleAuditService Mechanically

### Scope

- Add `backend/src/movies_feed/existing_title_audit.py`.
- Edit `backend/src/movies_feed/scanner.py`.
- Edit `backend/tests/test_existing_title_audit.py` and move audit-specific cases from `backend/tests/test_scanner.py`.

### Work

1. Introduce `ExistingTitleAuditService` with injected repositories, matcher, resolver, clock, configuration, and callbacks needed by current behavior.
2. Move title selection, occurrence clustering, AI batch handling, needs-review recording, suggestion inspection, proposal creation, and aggregate validation into it.
3. Keep the current data shapes and control flow unchanged.
4. Keep `ScannerService.recheck_existing_titles` as a compatibility delegate.
5. Keep ScanRun statistics mapping in scanner orchestration.
6. Move only audit-specific tests to the new test file; do not rewrite their assertions.

### Acceptance Criteria

- `ScannerService` no longer constructs `AuditProposal` directly.
- Existing audit tests retain the same behavior.
- The A1 contract mismatch still fails for the same reason.
- No matching, resolver, proposal, or persistence policy changes are introduced.

### Validation

```powershell
python -m unittest backend.tests.test_existing_title_audit backend.tests.test_scanner -v
```

## A3: Install the Production Apply Kill Switch

### Scope

- `backend/src/movies_feed/cli.py`
- `backend/src/movies_feed/scanner.py`
- `backend/tests/test_cli.py`

### Work

1. Add one explicit environment feature gate for non-dry-run proposal application.
2. Default the gate to disabled.
3. Remove proposal application from `mode=all` permanently.
4. Require `--proposal-id` for `apply-proposals`.
5. Require `--proposal-id` when `--reject-proposal` is used.
6. Reject proposal-specific arguments in every unrelated mode.
7. Allow explicit proposal dry-run while the production mutation gate is disabled.
8. Ensure blocked application returns configuration failure before repositories are mutated.

### Acceptance Criteria

- No default CLI invocation can mutate data through proposal application.
- `mode=all` never executes proposal application.
- Dry-run planning remains possible for one explicit proposal.
- Invalid argument combinations fail before scanner construction.

### Validation

```powershell
python -m unittest backend.tests.test_cli -v
```

## A4: Remove Destructive Workflow Entry Points

### Scope

- `.github/workflows/scanner.yml`
- `backend/tests/test_workflow_security.py`
- `DEPLOYMENT.md`

### Work

1. Remove `apply-proposals` from workflow mode options.
2. Remove proposal ID and reject inputs and their environment variables.
3. Keep existing shell-injection defenses for the remaining inputs.
4. Document that `all` is non-destructive.
5. Document that production proposal application is temporarily disabled during remediation.
6. Update workflow tests to assert that destructive dispatch inputs are absent.

### Acceptance Criteria

- Scheduled and manual GitHub workflows cannot dispatch proposal application.
- Remaining workflow input validation still passes.
- Documentation does not suggest an alternate production bypass.

### Validation

```powershell
python -m unittest backend.tests.test_workflow_security -v
```

## A5: Checkpoint Gate

Run once:

```powershell
python -m unittest discover -s backend/tests -v
```

The checkpoint passes when:

- The full backend suite passes after production changes.
- The A1 regression is either marked as an explicit expected failure or isolated with a clear note for B5; do not hide unrelated failures.
- The only intentional behavioral change is disabling destructive proposal application and removing it from `all`.

Proceed to [Checkpoint B](02_CHECKPOINT_B_PROPOSAL_CONTRACT.md).
