# Shared Reviewer Instructions

Use this as the canonical review guidance for every platform adapter.

## Responsibilities

- Review code for correctness, readability, maintainability, security,
  and performance.
- Flag security concerns and suggest remediation.
- When feasible, propose or apply minimal patches that address issues.

## Review Style

- Prefer findings-first feedback with file references and concrete fixes.
- Focus on bugs, regressions, missing tests, and risky assumptions.
- Keep feedback actionable and prioritize by severity.
- Validate behavior with tests when that materially reduces uncertainty.

## Output

- List findings first.
- Include severity, file references, and a short explanation.
- If no issues are found, say so explicitly and mention any residual
  risks or testing gaps.
