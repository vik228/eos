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
8. On a stalled or watched run, read the relevant scripts and logs before anything restarts - gather evidence first; a reconnect once overwrote the remote log.
9. Record the hypothesis and supporting evidence before `kb bug block`; a blocked ledger rejects records until `kb bug resume`.
10. Valid `kb bug record --kind` values are `classification`, `retrieval`, `reproduction`, `system_map`, `blast_radius`, `hypothesis`, `supporting`, `contradicting`, `disconfirmation`, `alternative_disposition`, `root_cause`, `failing_test`, `affected_cases`, `verification`, `uncertainty`, `durable_learning`, and `advance`.
11. Advance the phase stepwise with `kb bug record <id> --kind advance --file <phase-json> --kb <root> --json` where the file holds a JSON object like `{"phase": "<next>"}` along `new` -> `reproducing` -> `investigating` -> `root-caused` -> `fixing` -> `verifying`, then close with `kb bug complete`. `--value` stays a string and always fails phase validation, so always use `--file` for `advance`. `kb bug complete` reports one of three errors (`kb/src/eos_kb/investigations.py`, `complete_investigation`): the ledger must be `verifying` first ("investigation must be verifying before completion"); evidence gaps ("missing evidence: " naming the absent kinds); or a missing durable-learning decision ("durable-learning proposal decision is required", or "durable-learning proposal is required" when a required proposal has no `proposal_id`). Record `durable_learning` as a JSON object such as `{"required": false}` via `--file`. If `complete` fails, run `kb bug status`, record the missing kinds, and advance stepwise before retrying.

If faithful reproduction is blocked, record the blocker and keep the task blocked. Never present a guess as root cause.
