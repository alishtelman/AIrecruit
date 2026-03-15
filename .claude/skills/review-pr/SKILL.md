---
name: review-pr
description: Review a change set for regression risk, missing tests, compatibility issues, and security concerns.
allowed-tools: Read, Grep, Glob
---

Review the current change set.

Focus on:
1. Regression risk
2. Missing tests
3. Backward compatibility
4. Security implications
5. Overly broad or unnecessary edits

Return:
- findings
- severity
- exact files
- suggested fixes

Do not rewrite code. This skill is for analysis and review only.