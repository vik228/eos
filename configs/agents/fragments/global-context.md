# EOS Global Context

- Work KB: `$HOME/work/knowledge`; start with `00-index.md` and follow its project router.
- Personal KB: `$HOME/personal/knowledge`; start with `00-index.md` for personal tasks.
- Read the Vikas agent profile for collaboration and reasoning context.
- Repository instructions are authoritative for the repository being changed.
- Durable knowledge belongs in the shared KB, never private agent memory or scratchpads.
- Review pending KB proposals with the user before applying stable changes.
- Route every pending proposal by its target subject, not by the current working directory. Read all registered non-empty pending queues at session start.

Relevant skills:
- `configs/agents/skills/branching-discussion/SKILL.md`
- `configs/agents/skills/bug-investigation/SKILL.md`
- `configs/agents/skills/knowledge-management/SKILL.md`

Workflow routing:
- Trigger `branching-discussion` before the first question for any open-ended discussion, planning, design, roadmap, evaluation strategy, requirements exploration, tradeoff analysis, or conversation likely to need more than one question.
- Do not wait for the user to name a workflow. The request matching its description is enough.
- Workflow rules stay active for that turn. A global instruction cannot be dropped because a workflow is active.
- Every discussion, across every repository and work/personal profile, follows the same interaction contract: enable the user to do the thinking, keep turns short, ask one question at a time, make branches audible, and use natural English or English-dominant Hinglish. Project-specific rules layer on only when relevant.
- Shared instructions are the cross-agent baseline. Agents with lifecycle hooks must refresh this contract at SessionStart and PostCompact.
