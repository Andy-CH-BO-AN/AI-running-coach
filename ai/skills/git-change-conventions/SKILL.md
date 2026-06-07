---
name: git-change-conventions
description: Use when creating or naming branches, pull requests, or commits in this repository. Follow the repo's required type prefixes for branch and PR titles, and write detailed commit messages.
---

# Git Change Conventions

Use this skill whenever the task includes:

- creating a branch
- updating the readme
- naming a pull request
- writing commit messages
- proposing branch, PR, or commit naming conventions

## PR title format

Pull request titles must use this exact format:

- `<TYPE>: <summary>`

The allowed `<TYPE>` values are:

- `FEATURE:` new feature
- `FIX:` bug fix
- `REFACTOR:` code refactor with no behavior change
- `DOCS:` documentation only
- `TEST:` tests only
- `STYLE:` formatting-only changes such as linting or layout cleanup
- `PERF:` performance improvement
- `CHORE:` maintenance or miscellaneous housekeeping
- `CI:` continuous integration configuration or scripts

## Branch format

Git branch names cannot contain `:` or spaces, so branches must use this
compatible format instead:

- `<type>/<summary-in-kebab-case>`

Examples:

- `feat/add-weekly-fatigue-summary`
- `fix/handle-empty-garmin-heart-rate-payload`

## Required usage rules

1. Use the same logical type for the branch and PR title unless there
   is a clear reason not to.
2. Branch `type` uses the short lowercase prefix (e.g. `feat`), while
   the PR title uses the full allowed `TYPE` name (e.g. `FEATURE:`).
   See the mapping table in the PR creation section.
3. Keep the text after the prefix specific to the actual change.
4. Do not invent additional top-level prefixes unless the user
   explicitly changes the convention.
5. If a change spans multiple categories, choose the prefix that best
   describes the primary user-facing outcome.
6. Convert branch summaries to lowercase kebab-case.
7. PR descriptions should contain summary, why the change was needed, what was changed, and any important
   implementation or validation notes.

## Commit message rules

- Commit messages must be detailed, not terse.
- The subject line should clearly describe the intent and affected area.
- Prefer a multi-line commit message when the change is non-trivial.
- The body should summarize:
  - what changed
  - why the change was needed
  - any important implementation or validation notes

## Examples

- Branch: `feat/add-weekly-fatigue-summary`
- PR title: `FEATURE: add weekly fatigue summary to coach report`
- Branch: `fix/handle-empty-garmin-heart-rate-payload`
- PR title: `FIX: handle empty Garmin heart rate payload`
- Branch: `docs/add-shared-git-naming-conventions`
- PR title: `DOCS: add shared Git naming conventions for branch, PR, and commits`

## PR creation with GitHub CLI

When creating a pull request via `gh`, apply the conventions above:

```bash
gh pr create \
  --title "TYPE: summary" \
  --body "## Summary
<what this PR does>

## Why
<why the change was needed>

## Changes
- <file/area>: <description>

## Validation
- <tests run, manual checks, or screenshots>" \
  --base main
```

- Use `--draft` for work-in-progress PRs that are not ready for review.
- Add `--reviewer <handle>` when the team requires explicit reviewer
  assignment.
- Add `--label <label>` to categorise the PR when project labels exist.
- The PR title `TYPE` must use the allowed name from the PR title
  format section, not a literal uppercase of the branch prefix. Use the
  mapping below:

| Branch prefix | PR title TYPE |
|---------------|---------------|
| `feat`        | `FEATURE:`    |
| `fix`         | `FIX:`        |
| `refactor`    | `REFACTOR:`   |
| `docs`        | `DOCS:`       |
| `test`        | `TEST:`       |
| `style`       | `STYLE:`      |
| `perf`        | `PERF:`       |
| `chore`       | `CHORE:`      |
| `ci`          | `CI:`         |

## Output expectations

- When asked to create names, provide branch and PR title that follow
  this convention exactly.
- When asked to commit, write a detailed commit message that matches the
  change scope instead of a one-line shorthand.
