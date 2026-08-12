# Roadmap

EOS is evolving from a working macOS engineering distribution into a personal,
governed knowledge and context platform that can serve multiple AI-agent
harnesses.

The user retains direct control of the KB. Local execution is the default;
self-hosting on user-controlled infrastructure is an intended deployment model.

## Current Foundation

- Markdown-canonical personal and work knowledge spaces.
- OKF-compatible bundle parsing, validation, metadata, and generated routers.
- Project and subject routing.
- Retrieval budgets, search, freshness, and source-drift audits.
- Governed `propose -> review -> promote` changes.
- Session lifecycle, recovery, and structured bug investigations.
- Subject-aware capture, deduplication, and profile-scoped pending reminders.
- Shared skills and instructions across supported coding agents.
- Agent-assisted configuration of named profiles and workspaces.
- A tested macOS engineering reference integration.

## Next: Make the KB Core Independently Consumable

- Separate the knowledge-core installation path from the full workstation
  bootstrap without breaking the bundled distribution.
- Replace the thin Bash `eos` router with a stable cross-platform Python CLI.
- Define supported core operations independently of terminal/workspace tools.
- Publish the supported OKF compatibility profile and EOS-namespaced extension
  contract separately from runtime implementation details.
- Add portable configuration for KB roots, profiles, retrieval budgets, and
  governance policies.
- Document backup, restore, export, and self-hosted deployment boundaries.
- Add focused core verification that does not require macOS, tmux, or Neovim.

## Then: Skills and MCP Harness Access

- Package the knowledge-management workflows as installable skills for
  supported agent harnesses.
- Expose governed KB operations through MCP without granting arbitrary
  filesystem mutation.
- Preserve source attribution and approval records across harnesses.
- Ensure every harness adapter consumes the same OKF-compatible bundle rather
  than creating vendor-specific memory copies.
- Design privacy controls for context selection and disclosure.
- Design authentication, authorization, consent, and audit behavior for local
  and self-hosted remote access.
- Validate the model against at least one real web/app agent harness before
  declaring the integration contract stable.

The exact permission and delivery model is intentionally open. It will be
settled through a dedicated product and security discussion rather than assumed
in this roadmap.

## Expand Beyond Coding

- Provide example routes and skills for research, learning, writing, finance,
  health, and other personal knowledge workflows.
- Let each domain define its own sources, freshness rules, private context, and
  approval expectations.
- Keep domain integrations optional; the core must remain useful without the
  macOS engineering environment.
- Explore agent-harness web/app onboarding for users who do not work in a
  terminal.

## Later

- Broader operating-system support.
- Automated health and knowledge-quality reports.
- Optional team or organization knowledge spaces after the personal ownership
  model is mature.
- Additional storage and indexing adapters that preserve user ownership and
  OKF-compatible Markdown portability.

## Non-Goals for Now

- EOS-managed central hosting of user knowledge.
- Silent agent writes to curated knowledge.
- A proprietary knowledge format that locks users into EOS.
- Claiming a finished web/app permission model before it is designed and
  tested.
