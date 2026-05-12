# Codex Agents & Workflow

This repo uses shared markdown as the single source of truth for agent
behavior.

## Canonical Docs

- [`ai/shared/instructions.md`](../ai/shared/instructions.md)
- [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
- [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
- [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)
- [`ai/skills/python-review-qa-loop/SKILL.md`](../ai/skills/python-review-qa-loop/SKILL.md)
- [`ai/skills/python-review-qa-loop/agents/openai.yaml`](../ai/skills/python-review-qa-loop/agents/openai.yaml)
- [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
- [`ai/skills/readme-pm-review/agents/openai.yaml`](../ai/skills/readme-pm-review/agents/openai.yaml)

## Codex Adapters

- [`copilot-instructions.md`](copilot-instructions.md)
- [`agents/reviewer.agent.md`](agents/reviewer.agent.md)
- [`agents/qa.agent.md`](agents/qa.agent.md)
- [`agents/security.agent.md`](agents/security.agent.md)
- [`.codex/skills/python-review-qa-loop/SKILL.md`](skills/python-review-qa-loop/SKILL.md)
- [`.codex/skills/python-review-qa-loop/agents/openai.yaml`](skills/python-review-qa-loop/agents/openai.yaml)
- [`.codex/skills/readme-pm-review/SKILL.md`](skills/readme-pm-review/SKILL.md)
- [`.codex/skills/readme-pm-review/agents/openai.yaml`](skills/readme-pm-review/agents/openai.yaml)

Keep the adapters thin so the shared docs stay authoritative.

## Optional On-Demand Guides

- Use [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
  only when explicitly asking for a product-manager style README review.
- These repo-local skills are intended for this project only:
  `python-review-qa-loop` and `readme-pm-review`.
