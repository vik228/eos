# EOS Shared Agent Instructions

This file is the shared global instruction source for local coding agents.

## Shared Knowledge Base

- Work knowledge root: `$HOME/work/knowledge`; start at `00-index.md`.
- Personal knowledge root: `$HOME/personal/knowledge`; start at `00-index.md`.
- Read the configured agent profile for collaboration and reasoning context.
- The work and personal knowledge bases are the durable sources of truth.
- For every task, start at the matching root index and follow its project,
  area, and pattern routers. Read only relevant linked material.
- Repository-local instructions complement the knowledge base and remain
  authoritative for repository-specific architecture and contribution rules.
- Knowledge and memory content must live in the shared knowledge bases. Private
  agent memory may store only a reference to an index, never copied content.
- Before applying knowledge changes, read the relevant pending queue, review
  every proposal with the user, and apply only explicitly accepted items.
- Treat knowledge as curated context. Stable Markdown changes must use the EOS
  proposal, review, and promotion lifecycle.

## Global Working Rules

- Never use the em dash character. Use plain dash "-" instead.
- Preferred language is English or natural English-dominant Hinglish. Never
  write in Hindi.
- Never auto-add an agent name as a commit or pull-request co-author.
- Prefer quality, simplicity, robustness, scalability, and long-term
  maintainability over development cost.
- Reproduce bugs through the user-visible E2E path before implementing fixes.
- Treat UI quality, lint failures, test failures, and flakiness as real defects.
