---
name: bug-investigation
description: Use for bugs, regressions, failed tests, unexpected output, and production discrepancies.
---

# Bug Investigation

Use the `kb bug` ledger for every bug-shaped task:

1. `kb bug start --session <id> --symptom <text> --kb <root> --json`.
2. Retrieve relevant KB context and freshness; reproduce through the closest end-user path.
3. Map entrypoints, readers, writers, consumers, environments, flags, and blast radius.
4. Record hypotheses, supporting and contradicting evidence, and disconfirmation tests.
5. Do not implement until the ledger has a root cause and a failing test or executable reproduction.
6. Verify the original reproduction, negative and adjacent cases, regressions, lint, and remaining uncertainty.
7. Capture durable failure modes as proposals, then run `kb checkpoint` before completion.

If faithful reproduction is blocked, record the blocker and keep the task blocked. Never present a guess as root cause.
