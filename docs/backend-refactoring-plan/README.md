# Backend Refactoring Execution Plan

Date: 2026-08-31

This plan turns the findings in [`../BACKEND_REFACTORING_REVIEW_2026-08-31.md`](../BACKEND_REFACTORING_REVIEW_2026-08-31.md) into small implementation prompts suitable for Flash-class models.

Do not execute the entire plan in one session. Complete one numbered step at a time and begin the next checkpoint only after its gate passes.

## Plan Structure

| Checkpoint | Purpose | Steps | Full-suite gate |
| --- | --- | ---: | --- |
| [A](01_CHECKPOINT_A_ISOLATE_AND_DISABLE.md) | Characterize behavior, extract audit ownership, disable destructive apply | A1-A5 | Backend |
| [B](02_CHECKPOINT_B_PROPOSAL_CONTRACT.md) | Define one typed, versioned, idempotent proposal contract | B1-B10 | Focused tests only |
| [C](03_CHECKPOINT_C_ATOMIC_APPLICATION.md) | Implement bounded, transactional proposal application | C1-C8 | Backend + Firestore emulator |
| [D](04_CHECKPOINT_D_AUDIT_CORRECTNESS.md) | Fix validation invalidation and cluster recency | D1-D4 | Focused tests only |
| [E](05_CHECKPOINT_E_RULES_AND_CI.md) | Harden settings, workflow pins, and dependency process | E1-E6 | Rules + frontend + workflow |
| [F](06_CHECKPOINT_F_RELEASE.md) | Align documentation and safely re-enable manual application | F1-F5 | Complete release gate |

## Mandatory Execution Rules

Copy this section into the working context before every numbered step.

1. Execute exactly one numbered step. Do not combine adjacent steps.
2. Read only the files listed by that step plus directly imported symbols needed to understand them.
3. Preserve unrelated behavior and public APIs unless the step explicitly changes them.
4. Do not modify `legacy/`.
5. Use no live RSS, OMDb, Gemini, or production Firestore in tests.
6. Make the smallest edit that satisfies every acceptance criterion.
7. Run only the validation command listed for the step. Do not rerun it after success.
8. Do not run trailing-whitespace checks, Markdown validation, broad linting, repeated `git status`, or repeated `git diff`.
9. Do not reinstall dependencies when the existing environment satisfies the lockfile.
10. If Python, Node, or Java is unavailable, record one environment blocker and defer executable validation to CI. Do not repeatedly probe runtimes.
11. Stop if a prerequisite checkpoint is not green. Do not silently rebuild earlier work.
12. At completion, report changed files, acceptance criteria met, the single command run, and remaining blockers.

## Validation Budget

The command budget is deliberate. It avoids spending most of a session repeatedly proving the same baseline.

- One focused command after each implementation step.
- No command for documentation-only steps.
- Full backend suite only at A5, C8, and F4.
- Firestore emulator only at C8, E2, and F4.
- Frontend tests/typecheck/build only at E5 and F4.
- `npm ci` only when dependencies are absent or do not match `package-lock.json`.
- No formatting-only validation unless a formatter changed executable source.

A failed focused check may be rerun after repairing the same local defect. Do not expand scope while it is failing.

## Refactoring Decision

### Required

- Extract existing-title audit behavior from `backend/src/movies_feed/scanner.py` into `existing_title_audit.py`.
- Move audit-specific tests from `backend/tests/test_scanner.py` into `test_existing_title_audit.py`.
- Move the proposal domain contract into `audit_proposal.py`.
- Put the new application storage boundary in `proposal_application_store.py` and its Firestore implementation in `firestore_proposal_application_store.py`.
- Add focused `test_proposal_application_store.py` tests.

### Explicitly Not Required

Do not broadly split every model or repository. `models.py`, `repository.py`, and `firestore_repository.py` are large, but their existing sections are sufficiently cohesive. A general reorganization would increase migration risk and prompt scope without fixing the identified defects.

The extraction in Checkpoint A is intentionally mechanical. Do not combine it with behavior changes.

## Fixed Architecture Decisions

- Proposal application is disabled before repair work starts.
- `mode=all` permanently excludes proposal application.
- Production application is eventually restored only for one explicit proposal ID.
- Legacy proposals remain readable but are non-actionable until regenerated.
- New repair proposals use a typed schema and collision-resistant v3 identity.
- A repair uses one bounded Firestore transaction; partial multi-batch movement is forbidden.
- One proposal contains no more than 200 occurrences.
- The current browser admin settings path remains; Firestore Rules and client validation are tightened.
- Frontend proposal approval UI, automatic legacy migration, and hosted scanner migration are outside this plan.

## Overall Acceptance Criteria

The plan is complete only when all statements below are true:

- A scanner-generated proposal can be consumed without metadata key conversion or guessing.
- Incomplete, uncertain, legacy, stale, or review-only proposals cannot mutate catalog data.
- Audit reruns cannot reset an operator decision or collide across feeds.
- Proposal application cannot leave partially moved occurrences after a failed transaction.
- Meaningful occurrence changes invalidate prior validation; observation-only changes do not.
- `audit_days` is evaluated from occurrence observation recency per cluster.
- Nested settings values are rejected consistently by the client, backend, and Firestore Rules.
- Every active GitHub Action is pinned to a reviewed commit SHA.
- `mode=all` is non-destructive and production apply requires explicit confirmation.
- The complete automated and staging release gates pass.

## Quality Assessment

**Clarity: 9/10.** Every implementation unit names its files, behavior, acceptance criteria, and one validation action. Architectural decisions are fixed up front, reducing model improvisation.

**Granularity: 9/10.** The work is split into small steps with characterization tests before risky changes. The remaining inherently larger units are the mechanical audit extraction and the Firestore transaction implementation; splitting either further would create unstable intermediate APIs.

**Command efficiency: 9/10.** Full suites and emulators are reserved for checkpoint gates. The plan explicitly excludes whitespace/Markdown checks and repeated broad commands.

**Residual ambiguity: moderate only in Firestore SDK mechanics.** Checkpoint C fixes the required semantics, limits, and tests, but the exact transaction helper signatures should follow the installed Firebase Admin library rather than being invented in advance.

Recommended execution: six sessions minimum, one per checkpoint. Checkpoints B and C may require multiple sessions if each numbered step is delegated independently to a Flash model.
