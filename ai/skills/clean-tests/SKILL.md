---
name: clean-tests
description: Audit, add, rewrite, or remove tests while keeping them behavior-focused and refactor-resistant. Use whenever changing test files, reviewing test quality, deleting redundant coverage, asserting configuration, tightening mocks, or deciding whether a safety, schema, migration, compatibility, or external-contract test should remain exact.
---

# Clean Tests

Protect observable behavior without freezing harmless implementation choices; treat deletion as a coverage decision, not a line-count exercise.

## First principles

- Test outcomes visible through public APIs, persisted state, files, logs, or user output.
- Prefer one strong behavior test over several weaker implementation snapshots.
- Use an independent oracle; do not call production helpers to verify themselves.
- Keep exact assertions when exactness is the contract.
- Treat hard-coded data as evidence to evaluate, not an automatic defect.
- Make the smallest test change that preserves meaningful regression protection.

## Classify each candidate

### KEEP

Keep a test when it protects any of these contracts:
- security, privacy, authorization, secret redaction, or fail-closed behavior
- schema, migration, serialization, storage identity, or data compatibility
- external API payloads, protocol limits, retry keys, status handling, or vendor aliases
- deterministic facts such as dates, rounding, pace, zones, aggregates, or calendars
- documented business configuration, allowlists, safety caps, or priority policy
- explicitly promised byte-for-byte legacy output

Do not weaken these tests merely because they inspect exact values or call order.

### REWRITE

Rewrite a test when its contract matters but its oracle is coupled to implementation. Common signals:
- direct calls to private helpers instead of a stable public seam
- exact internal tuple, list, dict shape, or validator ordering
- full mock call sequences where only one ordering constraint matters
- names tied to preview models, provider versions, or temporary product labels
- complete production constant snapshots when membership or behavior is sufficient
- duplicated production mapping or algorithm used as the expected value
- exact prose assertions when only warning level, marker, count, or risk meaning matters

### DELETE

Delete only when all conditions hold:

1. The case protects no unique contract or guards obsolete behavior.
2. A named surviving test covers the same failure mode at an equal or higher level.
3. Removing the case would still detect a realistic regression in the behavior.
4. The case is not a safety, schema, migration, external, or compatibility guard.

If replacement evidence is uncertain, choose REWRITE or KEEP.

## Audit workflow

1. Read the production entrypoint, documentation, schema, and nearby tests.
2. State the observable behavior before judging individual assertions.
3. Find overlapping tests and identify every assertion unique to the candidate.
4. Classify the case as KEEP, REWRITE, or DELETE.
5. Name replacement coverage before deleting anything.
6. Run replacement tests before removing the weaker case.
7. Re-run the affected suite after cleanup.

## Rewrite patterns

- Replace private-helper tests with calls through the nearest existing public entrypoint.
- Assert final output and side effects, not every internal step.
- Replace exact ordered collections with set or membership checks when order is irrelevant.
- Assert required entries and invalid exclusions instead of an extensible full allowlist snapshot.
- Patch retry budgets with a small sentinel and assert behavior relative to that policy.
- Give fixture items unique markers, then verify preservation, order, and deduplication.
- Parse rendered DOM or returned data instead of scanning source fragments.
- Use real isolated persistence for transaction and roundtrip contracts.
- Test logs with stable event markers and secret non-disclosure, not full sentences.
- Keep exact mock ordering only for commits, locks, idempotency, or external sequencing contracts.

Do not add a new production API solely to make a test convenient; use the closest stable seam already owned by the module.

## Configuration tests

- Keep an exact allowlist when adding an item expands ingestion, permissions, billing, or risk.
- Keep an exact cap when documentation defines it as a safety or business policy.
- Rewrite an extensible fallback list to prove fallback order with neutral sentinel entries.
- Rewrite provider/model names to generic fixtures when only priority or retry behavior matters.
- Delete a constant snapshot when stronger behavior tests already exercise every relevant branch.

## Mock discipline

- Mock external boundaries, nondeterminism, expensive I/O, and failure injection points.
- Avoid mocking the unit's own algorithm or every collaborator in its call graph.
- Prefer spies that capture meaningful inputs over full `assert_called_once_with` snapshots.
- Assert absence of forbidden side effects when early exit or safety behavior matters.
- Preserve exact calls when the call itself is the public adapter contract.

## Required audit output

For every candidate, report:

- file, test name, and problem type
- why coupling lowers value
- behavior or contract that must remain protected
- KEEP, REWRITE, or DELETE
- concise replacement direction for REWRITE
- named replacement coverage for DELETE

Group final results into delete, rewrite, and keep sections.

## Verification

1. Run focused tests for each replacement before deletion, then all affected modules.
2. Run the repository core regression command.
3. Run DB tests only against guarded test databases when persistence is touched.
4. Run the full suite when environment support exists.
5. Record passed, failed, and skipped checks with reasons.
6. Use a fresh Reviewer, then a fresh QA pass for Python test changes.
7. Add a separate Security pass for DB, credentials, privacy, or injection coverage.

Stop and report the gap when required replacement coverage cannot be demonstrated.
