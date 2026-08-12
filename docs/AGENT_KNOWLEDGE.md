# Agent Knowledge Base

EOS installs one global instruction surface per agent profile and points each one at the shared work and personal knowledge bases.

## Active Files

| Agent | Active file | EOS source |
| --- | --- | --- |
| Codex default | `~/.codex/AGENTS.md` | `configs/agents/AGENTS.md` |
| Codex work | `~/.codex-work/AGENTS.md` | `configs/agents/AGENTS.md` |
| Codex personal | `~/.codex-personal/AGENTS.md` | `configs/agents/AGENTS.md` |
| Gemini-compatible tools | `~/.gemini/GEMINI.md` | `configs/agents/GEMINI.md` |
| Claude default | `~/.claude/CLAUDE.md` | `configs/agents/CLAUDE.md` |
| Claude work | `~/.claude-work/CLAUDE.md` | `configs/agents/CLAUDE.md` |
| Claude personal | `~/.claude-personal/CLAUDE.md` | `configs/agents/CLAUDE.md` |
| Opencode default | `~/.opencode/AGENTS.md` | `configs/agents/AGENTS.md` |
| Opencode work | `~/.opencode-work/AGENTS.md` | `configs/agents/AGENTS.md` |
| Opencode personal | `~/.opencode-personal/AGENTS.md` | `configs/agents/AGENTS.md` |

## Shared Work Knowledge

- Root: `$HOME/work/knowledge`
- Top-level index: `$HOME/work/knowledge/00-index.md`
- Top-level pending updates: `$HOME/work/knowledge/_pending-kb-updates.md`
- Work Project index: `$HOME/work/knowledge/projects/backend-project/00-index.md`
- Work Project pending updates: `$HOME/work/knowledge/projects/backend-project/_pending-kb-updates.md`

Agents should read the top-level index first, choose the relevant project, then follow only that project's linked files relevant to the current task.
For work tasks, the top-level index is the root router. Agents should follow Working Guidelines to `areas/coding-guidelines.md`, read all 10 standing engineering rules, follow relevant files under `patterns/`, and use `projects/backend-project/00-index.md` for Work Project project context.
Knowledge and memory content lives only in the shared work knowledge base. Agent-specific memory should store a reference to the top-level index, not copied KB content.
For `$HOME/work/backend-project`, agents must also read repo-local rules before writing code: `$HOME/work/backend-project/.claude/CLAUDE.md` and `$HOME/work/backend-project/AGENTS.md`.

## Shared Personal Knowledge

- Root: `$HOME/personal/knowledge`
- Top-level index: `$HOME/personal/knowledge/00-index.md`
- Top-level pending updates: `$HOME/personal/knowledge/_pending-kb-updates.md`
- Vikas agent profile: `$HOME/personal/knowledge/areas/vikas-agent-profile.md`

Agents should read the personal top-level index first for personal writing, learning, research, tooling, and non-work coding tasks. The personal KB uses the same router pattern as the work KB: the root index points to project, area, and pattern indexes, while the root pending index points to project-specific or area-specific pending queues.

EOS uses `eos-kb-capture` and `eos-kb-pending-reminder` as shared,
profile-parameterized implementations for Claude and Codex. Compatibility
wrappers and legacy `genesis-kb-*.sh` / `nova-kb-*.sh` paths route into these
EOS-owned scripts. Capture routes each proposal by its target path, emits valid
log frontmatter, and suppresses duplicate event captures. Reminders aggregate
only the active profile's KB root, so work sessions never surface personal
queues and personal sessions never surface work queues.

Capture also normalizes open checkbox blocks and removes repeats before and after each headless capture. Multiline proposals are compared after whitespace normalization, so PreCompact and SessionEnd cannot keep appending the same open item.

Claude's global pre-tool hook resolves target paths relative to each configured
KB root and blocks direct Write/Edit operations against stable KB Markdown at
any depth. `logs/` and `_pending-kb-updates.md` remain explicitly writable
working registers. Stable concepts must move through `kb propose`, explicit
`kb review`, and `kb promote`.

Every discussion uses the same interaction contract across repositories and profiles. The rendered instructions carry it to every supported agent. Claude additionally refreshes it at SessionStart and PostCompact; project-specific rules are layered only when relevant.

## Updating Instructions

Edit the EOS source files in `configs/agents/`, then run:

```bash
scripts/install-agent-instructions
scripts/install-work-knowledge-indexes
scripts/install-personal-knowledge-indexes
scripts/install-codex-work-mcps
scripts/install-antigravity-mcps
bootstrap/verify.sh
```

The installer backs up any existing active file before replacing it with a symlink.
The work knowledge index installer creates the top-level KB indexes only when missing. Use `scripts/install-work-knowledge-indexes --force` to refresh them from EOS templates with backups.
The personal knowledge index installer works the same way for `$HOME/personal/knowledge`. Use `scripts/install-personal-knowledge-indexes --force` to refresh the personal scaffold from EOS templates with backups.

## Codex Work MCPs

EOS reads Claude-style MCP entries from `~/.mcp.json` and installs them into `~/.codex-work/config.toml` inside a managed block. This keeps MCP credentials out of the EOS repo while making the work Codex profile use the same work servers.

```bash
scripts/install-codex-work-mcps
```

Only the work Codex profile is updated. Personal Codex remains separate.

## Antigravity MCPs

EOS reads Claude-style MCP entries from `~/.mcp.json` and installs them into Antigravity's MCP config files while preserving built-in Antigravity MCPs such as `sequential-thinking`.

```bash
scripts/install-antigravity-mcps
```

The default targets are `~/.gemini/config/mcp_config.json` and `~/.gemini/antigravity-ide/mcp_config.json`.

## Codex KB Lifecycle

Claude's work KB flow uses repo-local lifecycle hooks. Codex does not expose the same low-noise `SessionEnd` hook, so EOS uses the `codex-work` launcher for work sessions:

- before Codex starts in `~/work/backend-project`, it prints the pending KB proposal count from `projects/backend-project/_pending-kb-updates.md`
- after Codex exits, it finds the just-written `~/.codex-work/sessions/**.jsonl` transcript for backend-project
- it runs `scripts/codex-work-kb-capture`, which uses headless Codex to write a dated session log and append proposed KB updates
- curated KB docs and memory files are never edited directly by the capture step

Use this for work Codex:

```bash
CODEX_HOME=$HOME/.codex-work codex-work
```

`codex-work` starts Codex with `--cd <work-dir>`, `--sandbox danger-full-access`, `sandbox_permissions=["disk-full-read-access"]`, `sandbox_workspace_write.network_access=true`, `--add-dir <work-dir>`, and `--add-dir $HOME/work/knowledge` by default. This lets work sessions edit the repo, write Git refs, read/write the shared KB, and connect to local/staging services such as Postgres MCP targets from inside the Codex command sandbox. Use `CODEX_WORK_SANDBOX_MODE=workspace-write` only when you explicitly want a tighter sandbox and do not need Git metadata writes. To disable or override the read permission for one launch, set `CODEX_WORK_SANDBOX_CONFIG`. To disable network access for one launch, set `CODEX_WORK_NETWORK_ACCESS=0`. To disable the writable work directory for one launch, set `CODEX_WORK_ADD_WORK_DIR=0`. To disable the writable KB directory for one launch, set `CODEX_WORK_ADD_KB_DIR=0`.

## Smoke Tests

Codex work profile:

```bash
CODEX_HOME="$HOME/.codex-work" codex --ask-for-approval never exec --cd "$HOME/work/backend-project" --sandbox read-only "From your active instructions, answer with only the work knowledge index path."
```

Antigravity:

```bash
agy --print "From your active instructions, answer with only the work knowledge index path."
```

Gemini CLI OAuth is no longer supported for Gemini Code Assist individual accounts. Use Antigravity CLI through `agy`, or use Gemini CLI with `GEMINI_API_KEY` / Vertex auth if needed.
