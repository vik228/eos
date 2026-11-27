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
7. After any batch check-off, re-grep every registered queue for open `- [ ]` boxes before declaring the queues clear.
8. Every new doc declares `freshness: tracked` or `freshness: historical` in its frontmatter. New means absent from the gate activation record (`.eos/freshness-gate.json`), which `kb index` snapshots once from the existing docs and never changes after that; a missing, corrupt, or version-skewed gate fails closed instead of re-activating, as do a missing or unreadable review ledger (`.eos/reviews.jsonl`) or approvals log. Both `kb validate` (read-only) and `kb promote` refuse a new doc without the field. Existing docs without the field stay `unknown` (reported, not blocking) and gain it gradually.
9. `tracked` docs declare their own window (`review_every: 30d`). Expiry is last review plus window. A review is a review event written by `kb promote` and bound to the exact promoted content hash (direct-change approvals never write one); docs already tracked at activation use the activation timestamp while their content is unchanged. Any edit after the latest review reports stale until re-review; a bare `reviewed_at` edit never moves expiry, and `stale_after` is inert (kept for reference only). An expired tracked doc blocks only the session that used it: `kb search`/`context`/`show` cards record into the session record automatically (the usage log mirrors them when enabled), `kb related` suggestions never count, and direct reads need `kb session checkpoint --used-resource <resource>` (repo-relative paths work; absolute paths and `..` are rejected). Automatic hook capture of Read/cat paths is still a queued follow-up, so record direct reads by hand until then; other sessions get a warning via `kb stale`. Contradictions, source drift, and coverage drift still block every session.
10. Freshness values: Logs, pending queues, tutorials, dated records (ADR/audit/research/snapshot/one-off checklist) are `historical` and carry no `stale_after`; routers and environment/access references are `tracked`. Never key this off `type:`.

Route personal tasks through the personal KB first. Route work tasks through the work KB and its project index.
