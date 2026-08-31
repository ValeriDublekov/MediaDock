# Checkpoint E: Rules and CI

## Goal

Align nested settings validation across Firestore and the client, finish immutable workflow pinning, and document deterministic dependency installation.

## Prerequisites

- [Checkpoint D](04_CHECKPOINT_D_AUDIT_CORRECTNESS.md) completed.
- Node and Java are required for the checkpoint gate; use CI if unavailable locally.

## E1: Add Nested Settings Rules Regressions

### Scope

- `firebase/tests/rules.test.ts`
- Do not edit `firestore.rules`.

### Work

Add explicit admin-write cases for:

1. missing feed URL or type;
2. extra nested feed field;
3. non-string URL;
4. non-HTTPS URL;
5. empty or overlong feed name;
6. overlong URL;
7. unsupported feed type;
8. non-string exclusion item;
9. empty exclusion item;
10. overlong exclusion item;
11. valid boundary values.

Retain reader, disabled, unauthenticated, malformed top-level, and valid admin coverage.

### Acceptance Criteria

- Existing valid authorization tests pass.
- New malformed nested cases fail because current Rules accept them.
- No production Rules change is included.

### Validation

Run the Rules emulator test once with explicit project ID `demo-mediadock`.

## E2: Implement Nested Firestore Validation

### Scope

- `firestore.rules`
- `firebase/tests/rules.test.ts`

### Work

1. Preserve the exact top-level field allowlist.
2. Validate every feed value as an exact `{url, type}` map.
3. Require bounded non-empty feed names.
4. Require bounded HTTPS URLs.
5. Restrict type to `movie` or `series`.
6. Validate every exclusion item as a bounded non-empty string.
7. Keep existing list/map count and numeric limits.
8. Keep `updatedBy == request.auth.uid`.
9. Do not broaden any reader or unauthenticated access.

If Firestore Rules cannot safely validate dynamic map values with the desired contract, stop and document that limitation instead of implementing a partial rule that appears complete. The fallback decision is to deny browser settings writes and move them to a later server-side control plane.

### Acceptance Criteria

- All E1 cases pass.
- Valid current settings remain writable by admins.
- Reader, disabled, and unauthenticated writes remain denied.

### Validation

Run the Rules emulator test once with explicit project ID `demo-mediadock`.

## E3: Add Client-Side Settings Validation

### Scope

- `src/domain/settings.ts`
- `src/adapters/firestoreSettingsAdapter.ts`
- Add one focused settings adapter test under `src/test/`.
- Do not change `SettingsView` layout.

### Work

1. Narrow `RssFeedConfig.type` to `movie | series`.
2. Define client constants matching backend/Rules limits.
3. Add a pure settings validator.
4. Validate exact feed shape, names, HTTPS URLs, types, exclusions, and numeric limits.
5. Validate before `setDoc`.
6. Reject malformed settings with a user-safe error.
7. Assert that invalid data never reaches the mocked Firestore write.
8. Assert valid settings are sent unchanged except `updatedBy`.

### Acceptance Criteria

- Client validation matches the persisted Rules contract.
- No scanner credential or privileged token is added to the client.
- UI structure is unchanged.

### Validation

```powershell
npx vitest run src/test/firestoreSettingsAdapter.test.ts
```

Use the actual chosen test filename if local naming conventions require a different one.

## E4: Pin Every Active Workflow Action

### Scope

- `.github/workflows/ci.yml`
- `.github/workflows/pages.yml`
- `.github/workflows/scanner.yml`
- `backend/tests/test_workflow_security.py`

### Work

1. Enumerate every active `uses:` statement in the three workflow files.
2. Replace mutable version tags with reviewed 40-character commit SHAs.
3. Preserve action configuration and behavior.
4. Extend the static test to inspect all active workflow files.
5. Fail the test for any external action not pinned to a 40-character SHA.
6. Keep local action syntax supported if any local actions exist.

### Acceptance Criteria

- No mutable external action tag remains.
- The test does not hard-code only checkout/setup-python.
- Workflow functionality is otherwise unchanged.

### Validation

```powershell
python -m unittest backend.tests.test_workflow_security -v
```

## E5: Document Reproducible Dependency Installation

### Scope

- `LOCAL_DEVELOPMENT.md`
- `.github/workflows/ci.yml`
- `backend/pyproject.toml` only if package metadata requires clarification.
- Do not manually edit generated lockfile contents unless dependencies change.

### Work

1. Define `backend/requirements.lock` as the CI/deployment lock.
2. Keep compatible dependency ranges in `pyproject.toml` for package metadata.
3. Document one command/process for refreshing the backend lock.
4. Keep frontend CI on `npm ci` and `package-lock.json`.
5. Add `python -m pip check` after backend installation.
6. Do not duplicate exact dependency versions between manifest and lockfile manually.

### Acceptance Criteria

- CI installation is deterministic.
- Maintainers have one documented lock update procedure.
- No dependency is upgraded merely to complete this step.

### Validation

No standalone command. Validate with E6.

## E6: Checkpoint Gate

Run each relevant command once:

1. Rules emulator suite with project `demo-mediadock`.
2. Frontend unit suite.
3. `npx tsc --noEmit`.
4. `npm run build`.
5. `python -m unittest backend.tests.test_workflow_security -v`.
6. `python -m pip check` in the installed backend environment.

Do not run the full backend suite here.

Proceed to [Checkpoint F](06_CHECKPOINT_F_RELEASE.md).
