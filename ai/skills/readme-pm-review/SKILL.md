---
name: readme-pm-review
description: Use only when the user explicitly asks for a product-manager style review of a repository README. Read only the README first, do not infer undocumented features, and provide readability feedback, rewrite suggestions, and product-priority recommendations.
---

# README PM Review

Use this skill only when the user explicitly asks for:

- a PM review of `README.md`
- README readability feedback from a product perspective
- product-oriented README rewrite suggestions
- product prioritization ideas based only on README content

## Required scope

- Read `README.md` first.
- Base the analysis only on what the README actually says.
- Do not infer features, roadmap items, or user personas that are not
  supported by the README text.

## Tasks

1. Evaluate whether a first-time reader can understand:
   - what the product is
   - what problem it solves
   - who would use it
   - current project status
   - how to get started quickly
2. Suggest README improvements:
   - which sections are too engineering-heavy
   - which information should move earlier
   - which wording should sound more product-oriented
   - what a clearer README structure would be
3. Suggest product next steps based on the README's stated capabilities:
   - short-term priorities for the next 1-2 iterations
   - medium-term ideas
   - ideas that should not be prioritized now
   - reason, user value, and priority rationale for each suggestion

## Output format

Use exactly these section headings:

- `## README 可讀性評估`
- `## README 改寫建議`
- `## 產品需求建議`
- `## 建議優先順序`
