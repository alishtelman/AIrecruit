---
name: db-migration
description: Plan or review a database migration with rollback, compatibility, and risk checks.
---

Plan or review the database migration described in: $ARGUMENTS

Checklist:
1. Forward migration steps
2. Backward compatibility during rollout
3. Rollback strategy
4. Required application changes
5. Data backfill or cleanup needs
6. Test coverage and operational risks

Return:
- migration plan
- rollout order
- rollback plan
- risk list
- files likely to change