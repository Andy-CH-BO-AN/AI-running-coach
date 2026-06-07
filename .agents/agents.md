# Antigravity Agents Adapter

This file serves as a thin adapter for discovering Antigravity agents. All canonical agent instructions, behavior, and prompts are maintained in the [`ai/shared/`](../ai/shared/) directory. 

Do not duplicate the full shared agent content here. Instead, agents should read the canonical instructions linked below.

## Canonical Shared Agents

### QA Engineer
- **Canonical Source:** [`ai/shared/qa.agent.md`](../ai/shared/qa.agent.md)
- **Adapter Source:** [`.agents/agents/qa.agent.md`](agents/qa.agent.md)
- **Purpose:** QA engineer focused on test strategy, reproducing issues, and reporting.

### Reviewer
- **Canonical Source:** [`ai/shared/reviewer.agent.md`](../ai/shared/reviewer.agent.md)
- **Adapter Source:** [`.agents/agents/reviewer.agent.md`](agents/reviewer.agent.md)
- **Purpose:** Agent focused on conducting code reviews.

### Security
- **Canonical Source:** [`ai/shared/security.agent.md`](../ai/shared/security.agent.md)
- **Adapter Source:** [`.agents/agents/security.agent.md`](agents/security.agent.md)
- **Purpose:** Security agent for reviewing project safety and risk factors.

### UI/UX
- **Canonical Source:** [`ai/shared/uiux.agent.md`](../ai/shared/uiux.agent.md)
- **Adapter Source:** [`.agents/agents/uiux.agent.md`](agents/uiux.agent.md)
- **Purpose:** Dashboard UI/UX reviewer for testing layouts and usability.
