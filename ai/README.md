# AI configuration (single source of truth)

Maintain agent behavior, skills, and workflow docs under `ai/`. Platform folders
only contain thin adapters that point here.

## Layout

| Path | Purpose |
|------|---------|
| `ai/shared/instructions.md` | Default dev workflow (review → QA loop) |
| `ai/shared/reviewer.agent.md` | Code review |
| `ai/shared/qa.agent.md` | QA and testing |
| `ai/shared/security.agent.md` | Security review |
| `ai/shared/frontend-dashboard.agent.md` | Dashboard design and implementation |
| `ai/skills/*/SKILL.md` | On-demand skills |

## Platform adapters

| Tool | Adapter path | Notes |
|------|----------------|-------|
| **Cursor** | `.cursor/` | Rules, subagents, project skills |
| **Codex** | `.codex/` | `copilot-instructions.md`, agents, skills |
| **GitHub Copilot** | `.github/` | `copilot-instructions.md`, agents, skills |
| **Gemini** | `GEMINI.md` | Root pointer + project context |
| **Claude Code** | `CLAUDE.md` | Root pointer |
| **Windsurf** | `.windsurfrules` | Root pointer |

When you add or change behavior, edit files under `ai/` first, then update
adapters only if paths, discovery metadata, or tool-specific frontmatter
must change.

## Add a new shared skill

1. Create `ai/skills/<skill-name>/SKILL.md` with YAML frontmatter (`name`,
   `description`) and the full instructions.
2. Optionally add `ai/skills/<skill-name>/agents/openai.yaml` for Codex/GitHub
   skill UI metadata.
3. Add a thin adapter under each platform you use:
   - `.cursor/skills/<skill-name>/SKILL.md`
   - `.codex/skills/<skill-name>/SKILL.md`
   - `.github/skills/<skill-name>/SKILL.md`

Keep adapters minimal: reference `ai/skills/<skill-name>/SKILL.md` (or
`@ai/skills/<skill-name>/SKILL.md` in Cursor rules/skills where supported).

## Add a new shared agent

1. Add `ai/shared/<name>.agent.md` with the full prompt.
2. Add thin adapters:
   - `.cursor/agents/<name>.md` (Cursor subagent)
   - `.codex/agents/<name>.agent.md`
   - `.github/agents/<name>.agent.md`
