---
name: security
description: >-
  Security review for secrets, DB migrations, .env handling, Garmin credentials,
  and destructive test setup. Use when changes touch persistence, credentials,
  or external account flows.
model: inherit
readonly: true
---

# Cursor Subagent Adapter

Canonical instructions: `ai/shared/security.agent.md`

## Adapter rules

1. Read `ai/shared/security.agent.md` before acting.
2. Follow the canonical security instructions instead of duplicating logic in
   this adapter.
3. If this adapter and the canonical file diverge, treat
   `ai/shared/security.agent.md` as the source of truth.
