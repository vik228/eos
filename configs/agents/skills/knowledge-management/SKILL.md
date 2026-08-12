---
name: knowledge-management
description: Use for knowledge retrieval, KB changes, durable decisions, and session completion.
---

# Knowledge Management

1. Start with `kb context <query> --kb <root> --budget <units> --json`.
2. Inspect `kb stale --kb <root> --json` and freshness warnings before relying on retrieved material.
3. Treat Markdown as canonical and the shared KB as the only durable memory.
4. Record proposed stable changes with `kb propose`; never edit stable KB content directly.
5. Obtain explicit user approval, then use the required review and promotion commands.
6. Run `kb audit` and `kb checkpoint` before completing work.

Route personal tasks through the personal KB first. Route work tasks through the work KB and its project index.
