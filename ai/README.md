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
| `ai/skills/*/SKILL.md` | Shared skills and communication overlays |

## Local developer tools

For smoother AI-assisted frontend and dashboard work, configure a Chrome
DevTools MCP server in the local agent runtime when available. This lets agents
open the dashboard, inspect DOM/accessibility snapshots, read console and
network errors, and capture screenshots without leaving the coding loop.

Codex example:

```toml
[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest", "--channel", "stable", "--no-usage-statistics", "--no-performance-crux"]
```

Notes:

- This is a local developer-machine setting, not repository source code.
- Prefer an isolated Chrome profile for AI browser work; do not expose personal
  browsing sessions or sensitive pages to MCP tools.
- If Chrome MCP is unavailable, fall back to the headless Chrome screenshot
  commands documented in `ai/shared/frontend-dashboard.agent.md`.

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

## Default communication overlay

- `ai/skills/token-decrease/SKILL.md` is the default response-style overlay for
  repo-local agents.
- Platform adapters should load it automatically, while still allowing agents to
  switch back to normal phrasing when safety, irreversible actions, or clarity
  need more explicit wording.
- This repo-local canonical version is adapted from the external `caveman`
  skill by Julius Brussee:
  `https://github.com/JuliusBrussee/caveman/blob/main/skills/caveman/SKILL.md`
- Upstream MIT license notice is preserved in `THIRD_PARTY_NOTICES.md`.

## Third-party notices

- See `THIRD_PARTY_NOTICES.md` for upstream license notices that apply to
  adapted AI configuration content in this repository.

## Add a new shared skill

1. Create `ai/skills/<skill-name>/SKILL.md` with YAML frontmatter (`name`,
   `description`) and the full instructions.
2. Optionally add `ai/skills/<skill-name>/agents/openai.yaml` for Codex/GitHub
   skill UI metadata.
3. Add a thin adapter under each platform you use:
   - `.cursor/skills/<skill-name>/SKILL.md`
   - `.codex/skills/<skill-name>/SKILL.md`
   - `.github/skills/<skill-name>/SKILL.md`

Keep adapters minimal: tell the agent to read `ai/skills/<skill-name>/SKILL.md`
before acting. In Cursor, `@ai/...` includes work in `.cursor/rules/*.mdc` only;
project skills and subagents need explicit read instructions like the
`.codex/` and `.github/` adapters.

## Add a new shared agent

1. Add `ai/shared/<name>.agent.md` with the full prompt.
2. Add thin adapters:
   - `.cursor/agents/<name>.md` (Cursor subagent)
   - `.codex/agents/<name>.agent.md`
   - `.github/agents/<name>.agent.md`
