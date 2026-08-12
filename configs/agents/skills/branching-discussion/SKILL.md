---
name: branching-discussion
description: Mandatory for any open-ended discussion, planning, design, roadmap, evaluation strategy, requirements exploration, tradeoff analysis, or conversation likely to need more than one question. Trigger before the first question without waiting for the user to name this skill.
---

# Branching Discussion

The conversation is not the memory. A working document is. Every rule below exists to keep that document true.

1. Open a session doc in a durable location outside the code repository before the first question, and state its path to the user. It holds the question register, the return stack, and the learnings ledger. A session-scoped scratchpad is not durable. When the doc lives in the KB, put the working register under `logs/` and use valid frontmatter such as `title`, `type: Log`, and `date`; never bypass the KB proposal flow to create a stable concept.
2. Ask one question at a time. Record the answer and its implication before asking the next.
3. Give every question an id and a state: `pending`, `answered`, `answered-by-branch`, `reworded`, `moot`, or `blocked`. Emergent questions get ids in the same scheme; never run two numbering schemes in one doc.
4. When the discussion departs from a question, push one line onto the return stack: where we were, and why we left. Branching is normal and usually more valuable than the question that spawned it, so make it cheap rather than discouraged.
5. When a branch closes, run the close-out pass: write the learnings, re-score every open question against them, pop the stack. Report the diff, never the transcript.
6. A learning that changes no question is a note, not a learning. Notes belong in the doc body; only question-changing learnings enter the ledger.
7. Verify claims against the source before recording them as facts. Mark anything unverified as unverified.
8. At session end, hand the doc to `knowledge-management`: propose what is durable and leave the rest in the session doc.

## Evolving this skill

This skill is expected to improve with use. Discussion technique is learned, not designed once.

9. When a technique demonstrably helps or fails in a real discussion, record it in the session doc under "skill feedback": what happened, and what rule would have prevented or produced it.
10. Propose the amendment through the KB proposal flow and obtain explicit approval before editing this file. Never edit it silently.

## Conduct

11. Propose closing a branch and wait for the user's confirmation before popping the return stack. A "settled" heading inside a branch is not confirmation.
12. Keep turns short and conversational. One idea, then one question. Prose, not tables. Heavy structure belongs in the document, never in the reply. If a turn needs headings to be followed, it is too long.
13. Make branching audible. Name the departure and the reason on the way out, name the return on the way back. The other person should never have to ask which question is live.
14. Enable the other person to think in a direction instead of reaching the conclusion for them. Lay out the fork and let them choose the branch.
15. Never form a hypothesis and validate it yourself in the same turn. If the answer looks clear, surface the choice instead of closing it.
16. Lead toward a design conversationally. Do not present a finished design and ask for approval, because that turns a discussion into a review.
