# Custom Agents & Workflow

This project uses two custom agents and a strict review→QA workflow for all code and test changes.

## Agents

- **QA Agent**: Automatically writes, runs, and fixes tests. See `.github/agents/qa.agent.md`.
- **Reviewer Agent**: Reviews code for logic, maintainability, security, and performance. See `.github/agents/reviewer.agent.md`.

## Workflow

All changes to `src/`, `tests/`, or Python files must follow this loop:

1. Implement the minimal change.
2. Run tests locally.
3. Submit to the Reviewer agent for code review.
4. If approved, submit to the QA agent for full test and exploratory testing.
5. If QA fails, fix and return to Reviewer. Repeat until both approve.

## Example Prompts

- QA: `Add unit tests for src/preprocessing/data_processor.py and run them.`
- Reviewer: `Review the latest commit in src/ingestion/garmin_client.py for performance and security.`

See `.github/copilot-instructions.md` for full details.
