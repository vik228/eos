---
title: Personal Knowledge Base
type: Index
---
# Personal Knowledge Base

This is the top-level router for personal knowledge. Agents should start here for personal tasks, choose the relevant area or project, then read that area's own index before opening deeper files.

## Global Agent Context

- Agent profile: [areas/agent-profile.md](areas/agent-profile.md) - customizable communication style, collaboration preferences, and reasoning expectations.

## Projects

- EOS: [projects/eos/00-index.md](projects/eos/00-index.md) - durable routing and collaboration context for the `~/personal/eos` workspace.

When a personal project needs durable knowledge, add:

- Project index: `projects/<project-name>/00-index.md`
- Pending updates: `projects/<project-name>/_pending-kb-updates.md`
- Repo or workspace: absolute path to the project
- Summary: one sentence describing the project and what knowledge belongs there

## Areas

No personal area indexes are registered yet.

Use `areas/` for cross-project personal knowledge such as learning tracks, writing preferences, research notes, personal systems, reusable prompts, and decision logs.

## Common Patterns & Tutorials

No personal patterns are registered yet.

Use `patterns/` for reusable workflows, checklists, templates, and tutorials that are not tied to one project.

## How Agents Should Use This

1. Start with this top-level index for personal tasks.
2. Choose the project, area, or pattern that matches the current task.
3. Read that section's `00-index.md` when one exists.
4. Open only the linked files that are relevant to the task.
5. Treat personal knowledge files as curated context. Do not edit them unless explicitly asked or after user approval.
