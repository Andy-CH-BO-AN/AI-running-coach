# AI agent instructions (Cursor)

Canonical configuration lives in [`ai/`](ai/README.md). Do not duplicate workflow
rules here; adapters under `.cursor/` point to `ai/`.

## Read first

- Workflow: [`ai/shared/instructions.md`](ai/shared/instructions.md)
- Default communication overlay: [`ai/skills/token-decrease/SKILL.md`](ai/skills/token-decrease/SKILL.md)
- Reviewer: [`ai/shared/reviewer.agent.md`](ai/shared/reviewer.agent.md)
- QA: [`ai/shared/qa.agent.md`](ai/shared/qa.agent.md)
- Security: [`ai/shared/security.agent.md`](ai/shared/security.agent.md)
- Dashboard: [`ai/shared/frontend-dashboard.agent.md`](ai/shared/frontend-dashboard.agent.md)

## Cursor-specific entry points

- Always-on rule: [`.cursor/rules/ai-workflow.mdc`](.cursor/rules/ai-workflow.mdc)
- Subagents: [`.cursor/agents/`](.cursor/agents/)
- Skills: [`.cursor/skills/`](.cursor/skills/)

## Project constraints (summary)

- Deterministic facts (distance, dates, aggregates) are computed in Python
  (`src/preprocessing/coach_context.py`); the LLM interprets coaching context
  only.
- Dashboard is Vanilla HTML/JS/CSS with no build step.
- Data stays local; no cloud deployment architecture.

## Default style

- Load [`ai/skills/token-decrease/SKILL.md`](ai/skills/token-decrease/SKILL.md)
  by default for concise responses.
- Fall back to normal phrasing when safety, irreversible actions, or clarity
  need more explicit wording.

For Gemini-specific notes, see [`GEMINI.md`](GEMINI.md).
