# Shared Security Instructions

Use this as the canonical security review guidance for every platform
adapter.

## Responsibilities

- Review code and configuration for exposed secrets, unsafe defaults,
  overly broad permissions, risky network behavior, and destructive data
  operations.
- Check tracked files for hardcoded credentials, tokens, connection
  strings with passwords, private keys, and personal data.
- Verify local-only examples use placeholders or environment variables
  instead of real-looking secrets.
- Review database changes for migration safety, test isolation, and
  accidental production data mutation risks.
- Review external API workflows for rate-limit handling and safe retry
  behavior.

## Security Checklist

- No tracked file should contain real credentials or realistic default
  passwords.
- `.env` may contain local secrets but must remain git ignored.
- `.env.example`, README examples, Docker Compose, Alembic config, tests,
  and reports should use placeholders or variable interpolation.
- DB tests must not drop or reset a production or local main database.
- Destructive test setup must be isolated to test databases, temporary
  schemas, transactions, or rollbacks.
- Do not call real Garmin APIs during security review unless explicitly
  requested by the human maintainer.

## Output

- Lead with findings ordered by severity: `critical`, `normal`, `minor`,
  `suggestion`.
- Include file references and concrete remediation steps.
- If no issues are found, say so explicitly and mention any remaining
  assumptions or residual risk.
- Include the commands used for validation when relevant.
