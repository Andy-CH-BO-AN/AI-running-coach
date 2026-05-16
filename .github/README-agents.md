# GitHub Agents & Workflow

This repo uses shared markdown as the single source of truth for agent
behavior.

## Canonical Docs

- [`ai/shared/instructions.md`](../ai/shared/instructions.md)
- [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
- [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
- [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)
- [`ai/shared/frontend-dashboard.agent.md`](../ai/shared/frontend-dashboard.agent.md)
- [`ai/skills/python-review-qa-loop/SKILL.md`](../ai/skills/python-review-qa-loop/SKILL.md)
- [`ai/skills/python-review-qa-loop/agents/openai.yaml`](../ai/skills/python-review-qa-loop/agents/openai.yaml)
- [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
- [`ai/skills/readme-pm-review/agents/openai.yaml`](../ai/skills/readme-pm-review/agents/openai.yaml)
- [`ai/skills/git-change-conventions/SKILL.md`](../ai/skills/git-change-conventions/SKILL.md)
- [`ai/skills/git-change-conventions/agents/openai.yaml`](../ai/skills/git-change-conventions/agents/openai.yaml)

## Platform adapters

| Tool | README |
|------|--------|
| Cursor | [`.cursor/README-agents.md`](../.cursor/README-agents.md) |
| Codex | [`.codex/README-agents.md`](../.codex/README-agents.md) |
| GitHub | this file |
| Gemini | [`GEMINI.md`](../GEMINI.md) |

## GitHub Adapters

- [`copilot-instructions.md`](copilot-instructions.md)
- [`agents/reviewer.agent.md`](agents/reviewer.agent.md)
- [`agents/qa.agent.md`](agents/qa.agent.md)
- [`agents/security.agent.md`](agents/security.agent.md)
- [`agents/frontend-dashboard.agent.md`](agents/frontend-dashboard.agent.md)
- [`.github/skills/python-review-qa-loop/SKILL.md`](skills/python-review-qa-loop/SKILL.md)
- [`.github/skills/python-review-qa-loop/agents/openai.yaml`](skills/python-review-qa-loop/agents/openai.yaml)
- [`.github/skills/readme-pm-review/SKILL.md`](skills/readme-pm-review/SKILL.md)
- [`.github/skills/readme-pm-review/agents/openai.yaml`](skills/readme-pm-review/agents/openai.yaml)
- [`.github/skills/git-change-conventions/SKILL.md`](skills/git-change-conventions/SKILL.md)
- [`.github/skills/git-change-conventions/agents/openai.yaml`](skills/git-change-conventions/agents/openai.yaml)

Keep the adapters thin so the shared docs stay authoritative.

## Optional On-Demand Guides

- Use [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
  only when explicitly asking for a product-manager style README review.
- Use [`ai/skills/git-change-conventions/SKILL.md`](../ai/skills/git-change-conventions/SKILL.md)
  when creating a branch, naming a PR, or writing commit messages.
- Use [`ai/shared/frontend-dashboard.agent.md`](../ai/shared/frontend-dashboard.agent.md)
  when designing or implementing the AI running coach dashboard.
- These GitHub-side skill adapters only reference the canonical skill
  definitions in `ai/skills/`, including `git-change-conventions`.
