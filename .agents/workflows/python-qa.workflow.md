# Python Dev and QA Workflow (Antigravity Adapter)

This workflow outlines the standard procedure for Python development and testing. Do not duplicate instructions here; always read the canonical sources first.

## Prerequisites
1. Read the default dev workflow: [`ai/shared/instructions.md`](../../ai/shared/instructions.md)
2. Activate communication overlay: [`ai/skills/token-decrease/SKILL.md`](../../ai/skills/token-decrease/SKILL.md)

## Steps
1. **Develop**: Write your code changes. Follow the loop described in the QA loop skill: [`ai/skills/python-review-qa-loop/SKILL.md`](../../ai/skills/python-review-qa-loop/SKILL.md).
2. **Review**: Check your code against the reviewer guidelines: [`ai/shared/reviewer.agent.md`](../../ai/shared/reviewer.agent.md).
3. **Security Audit**: Ensure safety by referencing: [`ai/shared/security.agent.md`](../../ai/shared/security.agent.md).
4. **Test/QA**: Use the QA agent instructions to ensure test coverage and reproducibility: [`ai/shared/qa.agent.md`](../../ai/shared/qa.agent.md).
5. **Commit**: Apply git changes according to conventions: [`ai/skills/git-change-conventions/SKILL.md`](../../ai/skills/git-change-conventions/SKILL.md).
