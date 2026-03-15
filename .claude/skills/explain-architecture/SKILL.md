---
name: explain-architecture
description: Explain how a feature or subsystem works using read-only codebase research.
agent: researcher
---

Explain the architecture for: $ARGUMENTS

Process:
1. Identify entry points.
2. Map major modules and responsibilities.
3. Trace key call paths or data flow.
4. Note assumptions, config, and external dependencies.
5. Highlight fragile or surprising parts.

Return:
- summary
- file map
- request/data flow
- important caveats