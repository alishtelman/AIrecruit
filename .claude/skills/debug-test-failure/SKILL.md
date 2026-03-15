---
name: debug-test-failure
description: Diagnose a failing test or CI failure with minimal context growth. Prefer isolated investigation and concise findings.
agent: test-runner
---

Debug the failing test, CI job, or log pattern described in: $ARGUMENTS

Process:
1. Identify the narrowest relevant test command.
2. Run only the needed tests or checks.
3. Summarize failures by pattern, not by raw log volume.
4. Trace the likely code path causing the failure.
5. Suggest the smallest credible fix.

Return:
- failing scope
- root-cause hypothesis
- exact files to inspect or edit
- smallest next action