# Codex Agents & Workflow

This repo uses shared markdown as the single source of truth for agent
behavior.

## Canonical Docs

- [`ai/shared/instructions.md`](../ai/shared/instructions.md)
- [`ai/skills/token-decrease/SKILL.md`](../ai/skills/token-decrease/SKILL.md)
- [`ai/skills/token-decrease/agents/openai.yaml`](../ai/skills/token-decrease/agents/openai.yaml)
- [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
- [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
- [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)
- [`ai/shared/uiux.agent.md`](../ai/shared/uiux.agent.md)
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
| Codex | this file |
| GitHub | [`.github/README-agents.md`](../.github/README-agents.md) |
| Gemini | [`GEMINI.md`](../GEMINI.md) |

## Codex Adapters

- [`copilot-instructions.md`](copilot-instructions.md)
- [`agents/reviewer.agent.md`](agents/reviewer.agent.md)
- [`agents/qa.agent.md`](agents/qa.agent.md)
- [`agents/security.agent.md`](agents/security.agent.md)
- [`agents/uiux.agent.md`](agents/uiux.agent.md)
- [`.codex/skills/python-review-qa-loop/SKILL.md`](skills/python-review-qa-loop/SKILL.md)
- [`.codex/skills/python-review-qa-loop/agents/openai.yaml`](skills/python-review-qa-loop/agents/openai.yaml)
- [`.codex/skills/readme-pm-review/SKILL.md`](skills/readme-pm-review/SKILL.md)
- [`.codex/skills/readme-pm-review/agents/openai.yaml`](skills/readme-pm-review/agents/openai.yaml)
- [`.codex/skills/git-change-conventions/SKILL.md`](skills/git-change-conventions/SKILL.md)
- [`.codex/skills/git-change-conventions/agents/openai.yaml`](skills/git-change-conventions/agents/openai.yaml)
- [`.codex/skills/token-decrease/SKILL.md`](skills/token-decrease/SKILL.md)
- [`.codex/skills/token-decrease/agents/openai.yaml`](skills/token-decrease/agents/openai.yaml)

Keep the adapters thin so the shared docs stay authoritative.

## Default Communication Overlay

- Load [`ai/skills/token-decrease/SKILL.md`](../ai/skills/token-decrease/SKILL.md)
  by default for concise replies.
- Switch to normal wording when safety, irreversible actions, or clarity need
  more explicit phrasing.

## Optional On-Demand Guides

- Use [`ai/skills/readme-pm-review/SKILL.md`](../ai/skills/readme-pm-review/SKILL.md)
  only when explicitly asking for a product-manager style README review.
- Use [`ai/skills/git-change-conventions/SKILL.md`](../ai/skills/git-change-conventions/SKILL.md)
  when creating a branch, naming a PR, or writing commit messages.
- Use [`ai/shared/uiux.agent.md`](../ai/shared/uiux.agent.md)
  when reviewing the AI running coach dashboard for UX, accessibility, and
  visual quality issues.
- These repo-local skills are intended for this project only:
  `python-review-qa-loop`, `readme-pm-review`,
  `git-change-conventions`, and `token-decrease`.
