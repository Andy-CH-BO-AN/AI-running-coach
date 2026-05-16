# Cursor agents & workflow

This repo keeps **canonical** agent and skill content in [`ai/`](../ai/README.md).
Files under `.cursor/` are thin Cursor adapters only.

## Canonical docs

- [`ai/shared/instructions.md`](../ai/shared/instructions.md)
- [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
- [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
- [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)
- [`ai/shared/frontend-dashboard.agent.md`](../ai/shared/frontend-dashboard.agent.md)
- [`ai/skills/python-review-qa-loop/SKILL.md`](../ai/skills/python-review-qa-loop/SKILL.md)
- [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
- [`ai/skills/git-change-conventions/SKILL.md`](../ai/skills/git-change-conventions/SKILL.md)

## Cursor adapters

| Kind | Path |
|------|------|
| Always-on workflow | [`.cursor/rules/ai-workflow.mdc`](rules/ai-workflow.mdc) |
| Dashboard scope | [`.cursor/rules/dashboard.mdc`](rules/dashboard.mdc) |
| Subagents | [`.cursor/agents/`](agents/) |
| Project skills | [`.cursor/skills/`](skills/) |
| Root pointer | [`AGENTS.md`](../AGENTS.md) |

Subagents and skills use `@ai/...` includes so Cursor loads the canonical
markdown without duplicating it. If an include fails, read the linked `ai/`
file directly.

## On-demand usage

- **Reviewer / QA / Security:** delegate via subagents or follow the shared
  docs in the review loop.
- **`python-review-qa-loop`:** Python changes in `src/`, `tests/`, or workflow
  docs.
- **`git-change-conventions`:** branches, PR titles, commit messages.
- **`readme-pm-review`:** only when explicitly asked for a PM-style README
  review.
- **`frontend-dashboard`:** dashboard UI, adapters, weekly metrics, evidence
  links.
