# Changelog

## Unreleased

- Added the OKF-compatible shared knowledge runtime, bounded retrieval,
  freshness and coverage auditing, proposal governance, recoverable sessions,
  bug investigation gates, migration tooling, agent policy adapters, wrappers,
  scheduled audits, and adherence benchmarks.
- Added an optional TypeSafe Jev decision layer for retrieval: opt-in `--jev`
  flags on `kb search` and `kb context`, a standalone `scripts/eos-jev-filter`,
  work/personal API key routing, and graceful BM25 fallback.
- Fixed workspace-scoped `kb search` and `kb context` returning no results when
  concepts lack an `eos.project` tag. A concept's project now falls back to its
  `projects/<slug>/` path, and concepts outside `projects/` stay visible as
  shared knowledge under every project scope.
- Fixed child processes of a long-lived EOS session ignoring `.eos.local`
  changes. The config guard is no longer exported, and `scripts/eos-jev-filter`
  now loads EOS config so `status` reflects configured keys.

## 0.1.0 - 2026-07-01

- Created EOS repository structure.
- Migrated v1 dotfiles into modular EOS configs.
- Added semantic tmux workspace commands.
- Added bootstrap, verification, tests, docs, and ADRs.
- Added keybindings reference and productivity guide.
- Defaulted Claude to auto permission mode and Codex to no approval prompts in EOS workspaces.
- Made the backend workspace directory configurable with `EOS_BACKEND_DIR`.
- Made backend Neovim launch with the backend directory explicitly.
- Kept agent tmux windows open after normal Claude/Codex/Gemini exits.
- Made research Neovim launch with the resolved research directory explicitly.
