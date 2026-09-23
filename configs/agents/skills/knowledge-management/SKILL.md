---
name: knowledge-management
description: Use for knowledge retrieval, KB changes, durable decisions, and session completion.
---

# Knowledge Management

1. Start with plain `kb context <query> --kb <root> --budget <units> --json`. For exact identifiers (error codes, file paths, symbols, ticket ids), stay plain. For natural-language or symptom queries, read the plain cards first; if they are weak (off-topic, only session logs, or no card answers the question), rerun the same query once with `--jev` for Jev query expansion and semantic re-ranking. Do not start with `--jev`, and do not escalate when the plain cards already answer the question. `--jev-profile work|personal` is needed only when the key is not derived from the KB path; without a Typesafe key `--jev` falls back to plain BM25. Calls are logged locally; `scripts/eos-kb-usage` summarizes escalations.
2. Inspect `kb stale --kb <root> --json` and freshness warnings before relying on retrieved material.
3. Treat Markdown as canonical and the shared KB as the only durable memory.
4. Record proposed stable changes with `kb propose`; never edit stable KB content directly.
5. Obtain explicit user approval, then use the required review and promotion commands.
6. Run `kb audit` and `kb checkpoint` before completing work.

Route personal tasks through the personal KB first. Route work tasks through the work KB and its project index.
