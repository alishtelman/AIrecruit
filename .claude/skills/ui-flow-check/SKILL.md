---
name: ui-flow-check
description: Validate a Next.js user flow with playwright-cli. Prefer this over Playwright MCP for routine checks and regression testing.
allowed-tools: Bash, Read, Grep, Glob
---

Validate this flow: $ARGUMENTS

Rules:
1. Use playwright-cli, not Playwright MCP.
2. Keep the run targeted and short.
3. Prefer smoke checks over broad exploration.
4. Save screenshot or trace only when a failure occurs.

Return:
- scenario tested
- result
- failing step
- screenshot/trace path if any
- smallest fix hypothesis