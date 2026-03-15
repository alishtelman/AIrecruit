---
name: fastapi-change
description: Make or review a FastAPI change with router, schema, service, migration, and test impact in mind.
---

Handle this FastAPI task: $ARGUMENTS

Checklist:
1. Identify affected router, schema, service, model, and dependency wiring.
2. Check SQLAlchemy async session usage.
3. Check whether Alembic migration is required.
4. Preserve backward compatibility for API contracts unless explicitly told otherwise.
5. Update or suggest tests.

Return:
- files to change
- migration needed or not
- contract risk
- minimal implementation plan