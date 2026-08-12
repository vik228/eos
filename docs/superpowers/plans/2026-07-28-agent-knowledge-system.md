# EOS Agent Knowledge System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, migrate, and roll out the approved local OKF-compatible knowledge system for work and personal agents.

**Architecture:** A Python 3.12 package owns Markdown parsing, SQLite FTS5 retrieval, freshness, governance, sessions, investigations, and migration. Thin EOS shell wrappers install and invoke that package, while generated agent adapters and deterministic hooks give Claude, Codex, Gemini, and Antigravity one policy and lifecycle. Markdown remains canonical; SQLite, manifests, session events, and generated routers are rebuildable or auditable state.

**Tech Stack:** Python 3.12, argparse, sqlite3 FTS5, PyYAML, pytest, JSON Schema documents, Bash, Claude hooks, EOS profile wrappers.

**Source spec:** `docs/superpowers/specs/2026-07-28-okf-agent-knowledge-system-design.md`

---

## Delivery Boundaries

The work is one program with four sequential, independently verifiable phases:

1. Core bundle, index, retrieval, and generated-router runtime.
2. Freshness, governance, sessions, and bug-investigation gates.
3. Canonical agent policy, hooks, wrappers, bootstrap, and doctor integration.
4. Dry-run migration, explicit manifest approval, rollout, and adherence tests.

Do not apply a migration to either live KB until `kb migrate plan` has produced
an unchanged manifest hash and Vikas has explicitly approved that manifest.
Implementation and fixture migrations do not require this live-data gate.

Every public `kb` command has four checked-in golden CLI cases: success,
validation failure, recovery or explicit `recovery: not_applicable`, and text plus
JSON output shape. Task 1 creates the parameterized contract harness and placeholder
goldens. The task that implements a command must replace all four placeholders;
its commit cannot pass while any owned command still returns `not implemented`.
Command ownership is: Task 3 `init`; Task 4 `index` and `validate`; Task 5
`search`, `show`, `related`, `context`, and `status`; Task 6 `stale` and `audit`;
Task 7 `propose`, `review`, `promote`, and `deprecate`; Task 8 `checkpoint` and
`session`; Task 9 `bug`; Task 13 `migrate`.

## File Map

### Python runtime

- `kb/pyproject.toml`: package metadata, runtime dependency, pytest configuration.
- `kb/src/eos_kb/cli.py`: argparse command tree and exit-code contract.
- `kb/src/eos_kb/config.py`: paths, workspace registry, and environment overrides.
- `kb/src/eos_kb/model.py`: immutable concept, proposal, approval, session, and investigation records.
- `kb/src/eos_kb/frontmatter.py`: safe YAML parsing and normalized Markdown serialization.
- `kb/src/eos_kb/normalize.py`: content hashing and deterministic claim normalization.
- `kb/src/eos_kb/schema.py`: machine-readable schema loading and validation errors.
- `kb/src/eos_kb/storage.py`: atomic writes, locks, JSONL events, SQLite transactions, and recovery records.
- `kb/src/eos_kb/indexer.py`: concept discovery, FTS5 index, graph edges, manifests, and generated routers.
- `kb/src/eos_kb/retrieval.py`: search ranking, section extraction, related concepts, and bounded context.
- `kb/src/eos_kb/freshness.py`: source, time, contradiction, and coverage drift.
- `kb/src/eos_kb/governance.py`: proposal, review, promotion, deprecation, and direct-change approval.
- `kb/src/eos_kb/sessions.py`: session lifecycle, checkpoints, leases, and abnormal recovery.
- `kb/src/eos_kb/investigations.py`: mandatory bug lifecycle and evidence gates.
- `kb/src/eos_kb/migration.py`: inventory, plan, apply, backup, and rollback.

### Schemas, templates, policy, and fixtures

- `configs/kb/workspaces.yaml`: reproducible work/personal routing and coverage rules.
- `configs/kb/migration-scopes.yaml`: ordered, disjoint, exhaustive migration scopes.
- `configs/kb/schemas/*.json`: versioned concept, proposal, approval, session, investigation, registry, and migration schemas.
- `configs/kb/templates/`: scaffold and generated-router templates.
- `configs/agents/fragments/critical-rules.md`: short always-on policy kernel.
- `configs/agents/fragments/global-context.md`: KB and repository routing.
- `configs/agents/skills/knowledge-management/SKILL.md`: retrieval and proposal workflow.
- `configs/agents/skills/bug-investigation/SKILL.md`: reproduction, hypotheses, fix gate, and verification.
- `configs/agents/claude/settings.fragment.json`: attribution and hook configuration merged into profiles.
- `configs/agents/claude/hooks/eos-agent-hook`: deterministic Claude hook adapter.
- `kb/tests/fixtures/`: valid, invalid, drift, governance, session, migration, and benchmark bundles.
- `kb/tests/fixtures/cli/`: per-command success, failure, recovery, text, and JSON goldens.

### Shell integration and docs

- `scripts/kb`: stable CLI entrypoint.
- `scripts/setup-kb`: isolated runtime provisioning.
- `scripts/render-agent-instructions`: deterministic adapter and skill renderer.
- `scripts/install-agent-instructions`: profile adapters, skills, and Claude settings installer.
- `scripts/lib-agent-session.sh`: shared wrapper session lifecycle.
- `scripts/claude-default`, `scripts/codex-default`: default-profile lifecycle wrappers.
- `scripts/claude-work`: work Claude wrapper.
- Modify `scripts/claude-personal`, `scripts/codex-work`, `scripts/codex-personal`, `scripts/antigravity-full`.
- Create `scripts/gemini-eos` with work/personal auto-routing.
- Modify `scripts/backend`, `scripts/research`, `scripts/agents`, `configs/wezterm/launch.lua`, and `configs/nvim/lua/config/eos_keymaps.lua` to call wrappers only.
- Modify `scripts/eos`, `bootstrap/bootstrap.sh`, and `bootstrap/verify.sh`.
- Create `configs/launchd/com.vikas.eos-kb-audit.plist.in`,
  `scripts/kb-audit-all`, and `scripts/install-kb-audit` for periodic local audits.
- Create `docs/AGENT_KNOWLEDGE_SYSTEM.md` and update `docs/AGENT_KNOWLEDGE.md`, `TESTING.md`, `INSTALL.md`, and `README.md`.

---

### Task 1: Package, Runtime Installer, and CLI Contract

**Files:**
- Create: `kb/pyproject.toml`
- Create: `kb/src/eos_kb/__init__.py`
- Create: `kb/src/eos_kb/cli.py`
- Create: `scripts/kb`
- Create: `scripts/setup-kb`
- Create: `kb/tests/test_cli.py`
- Create: `kb/tests/test_cli_contract.py`
- Create: `kb/tests/fixtures/cli/`
- Create: `tests/test_kb_runtime.sh`

- [ ] **Step 1: Write failing CLI and installer tests**

```python
def test_help_lists_stable_commands(run_cli):
    result = run_cli("--help")
    assert result.returncode == 0
    for command in (
        "init", "index", "validate", "search", "show", "related", "context",
        "status", "stale", "audit", "checkpoint", "propose", "review",
        "promote", "deprecate", "session", "bug", "migrate",
    ):
        assert command in result.stdout
```

The shell test must assert `scripts/kb` prefers `EOS_KB_PYTHON`, otherwise uses
`~/.local/share/eos/kb/.venv/bin/python`, and prints one actionable setup error.

- [ ] **Step 2: Run tests and verify red state**

Run: `uv run --project kb pytest kb/tests/test_cli.py kb/tests/test_cli_contract.py -q && tests/test_kb_runtime.sh`

Expected: FAIL because the package and scripts do not exist.

- [ ] **Step 3: Implement the package and command skeleton**

`cli.main(argv: Sequence[str] | None) -> int` must build the full command tree
listed in the test, including every nested session, bug, and migration command,
and return exit codes rather than calling `sys.exit` internally. Initially each
handler may return a typed `not implemented` result, but all four placeholder
goldens and command ownership metadata must exist so later task tests fail until
the handler is complete. Reserve exit codes:
`0` success, `2` CLI usage, `3` validation, `4` conflict, `5` blocked lifecycle,
and `6` recovery required.

- [ ] **Step 4: Provision and verify the isolated runtime**

Run: `EOS_KB_HOME=$(mktemp -d) scripts/setup-kb`

Expected: venv created, package installed, `scripts/kb --help` succeeds when
pointed at that venv.

- [ ] **Step 5: Run green tests and commit**

Run: `uv run --project kb pytest kb/tests/test_cli.py kb/tests/test_cli_contract.py -q && tests/test_kb_runtime.sh`

Expected: PASS.

Commit: `git commit -m "Add EOS knowledge CLI runtime"`

### Task 2: Concept Model, Frontmatter, Normalization, and Schemas

**Files:**
- Create: `kb/src/eos_kb/model.py`
- Create: `kb/src/eos_kb/frontmatter.py`
- Create: `kb/src/eos_kb/normalize.py`
- Create: `kb/src/eos_kb/schema.py`
- Create: `configs/kb/schemas/concept-v1.json`
- Create: `configs/kb/schemas/registry-v1.json`
- Create: `kb/tests/test_frontmatter.py`
- Create: `kb/tests/test_normalize.py`
- Create: `kb/tests/fixtures/concepts/`

- [ ] **Step 1: Write failing parser and normalization tests**

Cover BOM rejection, unsafe YAML tags, missing `type`, unknown type acceptance,
absent status defaulting to `stable`, generated concepts, normalized content
hashes, Unicode NFC, key sorting, ordered arrays, integer values, float rejection,
and duplicate keys after NFC normalization.

```python
def test_claim_normalization_is_canonical():
    assert normalize_claim({"b": 2, "a": ["e\u0301", True]}) == '{"a":["é",true],"b":2}'
```

- [ ] **Step 2: Verify the tests fail for missing modules**

Run: `uv run --project kb pytest kb/tests/test_frontmatter.py kb/tests/test_normalize.py -q`

- [ ] **Step 3: Implement immutable records and safe parsing**

Use frozen dataclasses. `Concept` must expose `resource`, `status`, `generated`,
`trust`, `freshness`, `authoritative`, headings, body, links, claims, and source
paths. Authority is derived and false for generated concepts.

- [ ] **Step 4: Implement versioned schema validation and golden errors**

Errors must include code, relative file, field path, and remediation. Runtime
validation may be handwritten but must produce values compatible with checked-in
JSON schema documents.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_frontmatter.py kb/tests/test_normalize.py -q`

Commit: `git commit -m "Add OKF concept parsing and schemas"`

### Task 3: Workspace Registry and Bundle Initialization

**Files:**
- Create: `kb/src/eos_kb/config.py`
- Create: `configs/kb/workspaces.yaml`
- Create: `configs/kb/templates/index.md`
- Create: `configs/kb/templates/pending-index.md`
- Create: `kb/tests/test_config.py`
- Create: `kb/tests/test_init.py`

- [ ] **Step 1: Write failing routing and scaffold tests**

Test longest-prefix matching, `~` expansion, environment-independent `$HOME`,
work/personal separation, unknown workspace failure, registry validation, and
idempotent `kb init` preserving existing content.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run --project kb pytest kb/tests/test_config.py kb/tests/test_init.py kb/tests/test_cli_contract.py -k 'config or init' -q`

- [ ] **Step 3: Implement routing and scaffolding**

Seed work project and research project mappings from the spec. Allow `EOS_KB_REGISTRY`,
`EOS_WORK_KNOWLEDGE_ROOT`, `EOS_PERSONAL_KNOWLEDGE_ROOT`, and test-local HOME
overrides. Never infer a work KB for an unknown personal path.

- [ ] **Step 4: Verify idempotence twice**

Run `kb init` twice against a temporary existing bundle and compare file hashes.

Expected: second run changes no bytes.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_config.py kb/tests/test_init.py kb/tests/test_cli_contract.py -k 'config or init' -q`

Expected: PASS with no changed hashes after the second scaffold run.

Commit: `git commit -m "Add knowledge workspace routing and scaffolds"`

### Task 4: Transactional Index, Graph, Manifest, and Generated Routers

**Files:**
- Create: `kb/src/eos_kb/storage.py`
- Create: `kb/src/eos_kb/indexer.py`
- Create: `configs/kb/schemas/manifest-v1.json`
- Create: `kb/tests/test_storage.py`
- Create: `kb/tests/test_indexer.py`
- Create: `kb/tests/fixtures/index-bundle/`

- [ ] **Step 1: Write failing index and recovery tests**

Cover FTS5 availability, concept and heading rows, forward/reverse links, broken
links, orphans, duplicate resources, supersession cycles, temporary database
replacement, failed rebuild preserving the prior database, and stale transaction
recovery.

- [ ] **Step 2: Write failing generated-router tests**

Assert routers include only immediate non-generated concepts and child
directories, carry `generated: true`, exclude `.eos`, remain byte-identical on
rerun, and fail strict validation after manual edits.

- [ ] **Step 3: Implement locking, atomic files, and SQLite schema**

Use `fcntl.flock` on macOS/Linux, temporary files in the destination directory,
`os.replace`, SQLite WAL, foreign keys, schema versioning, and a recovery record
before any multi-file promotion.

- [ ] **Step 4: Implement index and router generation**

Store concepts, headings, FTS text, links, claims, sources, and manifest hashes.
Router input hashes must exclude routers and `.eos` state.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_storage.py kb/tests/test_indexer.py kb/tests/test_cli_contract.py -k 'storage or index or validate' -q`

Expected: PASS, including failed-rebuild and stale-transaction recovery cases.

Commit: `git commit -m "Add transactional knowledge indexing"`

### Task 5: Ranked Search, Section Retrieval, and Hard Context Budgets

**Files:**
- Create: `kb/src/eos_kb/retrieval.py`
- Create: `kb/tests/test_retrieval.py`
- Create: `kb/tests/fixtures/retrieval-bundle/`

- [ ] **Step 1: Write failing exact and lexical retrieval tests**

Cover error strings, symbols, paths, tickets, flags, titles, tags, components,
symptoms, BM25 text, one-hop graph expansion, lifecycle filters, trust labels,
and explicit history queries.

- [ ] **Step 2: Write failing budget tests**

```python
def test_context_never_exceeds_budget(indexed_bundle):
    result = context(indexed_bundle, "booking family status", budget=2500)
    assert result.estimated_units <= 2500
    assert result.estimator == "utf8-bytes-div-2-ceil"
    assert result.warnings_reserved is True
```

Also assert the next complete result is omitted rather than truncated and that
freshness/contradiction warnings are reserved before prose.

- [ ] **Step 3: Implement ranking, section extraction, and output cards**

Keep output deterministic by adding resource ID as the final ranking tie-breaker.

- [ ] **Step 4: Add CLI JSON and text golden fixtures**

Every command must support stable machine-readable JSON where hooks consume it.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_retrieval.py kb/tests/test_cli_contract.py -k 'retrieval or search or show or related or context or status' -q`

Expected: PASS with every context result at or below its requested budget.

Commit: `git commit -m "Add bounded knowledge retrieval"`

### Task 6: Freshness, Claims, and Coverage Drift

**Files:**
- Create: `kb/src/eos_kb/freshness.py`
- Create: `configs/kb/schemas/freshness-v1.json`
- Create: `kb/tests/test_freshness.py`
- Create: `kb/tests/fixtures/git-source/`

- [ ] **Step 1: Write failing source and time drift tests**

Create temporary Git repositories to test blob changes, renames, ignored paths,
untracked paths, absent baselines, `stale_after`, and external content hashes.

- [ ] **Step 2: Write failing contradiction and coverage tests**

Cover same claim ID/same value, same ID/different value, deprecated concepts,
prose-only disagreement, implicit `source_paths`, explicit coverage mappings,
and exact `current`, `pending`, `drifted`, and `unknown` aggregation.

- [ ] **Step 3: Implement freshness derivation**

Use `git diff --find-renames --name-status` and `git rev-parse <rev>:<path>` via
argument arrays. No shell interpolation. Store derived state outside Markdown.

- [ ] **Step 4: Integrate warnings into search and checkpoint**

Invalid or unknown state must never be rendered as fresh.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_freshness.py kb/tests/test_cli_contract.py -k 'freshness or stale or audit' -q`

Expected: PASS for all four freshness dimensions and exact coverage states.

Commit: `git commit -m "Add deterministic knowledge freshness checks"`

### Task 7: Proposal Governance and Approval-Bound Promotion

**Files:**
- Create: `kb/src/eos_kb/governance.py`
- Create: `configs/kb/schemas/proposal-v1.json`
- Create: `configs/kb/schemas/approval-v1.json`
- Create: `kb/tests/test_governance.py`
- Create: `kb/tests/fixtures/governance-bundle/`

- [ ] **Step 1: Write failing lifecycle tests**

Test every allowed proposal transition and reject every unspecified transition.
Test new concepts with null base hashes, changed proposals after acceptance,
concurrent target edits, promotion result mismatch, deprecation, and terminal
states. Create parent and child session fixtures and assert a child may propose
and attach evidence but receives exit code `5` from promote, deprecate, and
direct-change approval.

- [ ] **Step 2: Write failing direct-change and transaction tests**

Strict validation must label a changed stable hash unreviewed. Generated routers
matching generator output are exempt. Simulate failures between proposal,
approval, concept, log, router, and manifest replacement and assert old live
state survives.

- [ ] **Step 3: Implement propose, review, promote, deprecate**

Append JSONL records with proposal ID, actor, timestamp, proposal hash, nullable
base hash, result hash, decision, and session evidence. Promotion must revalidate
all hashes while holding the KB write lock. Promotion, deprecation, and
direct-change review must load the session record and reject any record with
`parent_session_id`, even with a valid accepted proposal hash.

- [ ] **Step 4: Implement explicit conversational approval input**

Require `--actor`, `--session`, and exact proposal ID. Never expose a flag that
means implicit or blanket approval.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_governance.py kb/tests/test_cli_contract.py -k 'governance or propose or review or promote or deprecate' -q`

Expected: PASS, including child-session denial and injected transaction failures.

Commit: `git commit -m "Add approval-gated knowledge governance"`

### Task 8: Session Lifecycle, Checkpoints, and Abnormal Recovery

**Files:**
- Create: `kb/src/eos_kb/sessions.py`
- Create: `configs/kb/schemas/session-v1.json`
- Create: `kb/tests/test_sessions.py`
- Create: `tests/test_kb_session_wrapper.sh`

- [ ] **Step 1: Write failing state-transition tests**

Cover start, checkpoint as event, end, native-ID resume, explicit abandoned
resume, subagent parent, concurrent event files, stale PID/start-token recovery,
lease fallback, changed-path merge, and invalid transitions. Assert immutable
`parent_session_id` survives resume and recovery so governance cannot lose the
child restriction.

- [ ] **Step 2: Write a real killed-process E2E test**

Start a fixture wrapper, record a source change, kill it without `session end`,
run recover, and assert an abandoned session plus a next-audit drift warning.

- [ ] **Step 3: Implement append-only events and leases**

Do not mutate another active session baseline. Keep session UUIDs and proposal
UUIDs globally unique.

- [ ] **Step 4: Implement top-level `kb checkpoint` orchestration**

It must run audit then checkpoint the active session. `session end` must perform
that checkpoint before `active -> ended`.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_sessions.py kb/tests/test_cli_contract.py -k 'sessions or session or checkpoint' -q && tests/test_kb_session_wrapper.sh`

Expected: PASS, including the real killed-process recovery case.

Commit: `git commit -m "Add recoverable knowledge sessions"`

### Task 9: Bug-Investigation Ledger and Fix Gates

**Files:**
- Create: `kb/src/eos_kb/investigations.py`
- Create: `configs/kb/schemas/investigation-v1.json`
- Create: `kb/tests/test_investigations.py`
- Create: `kb/tests/fixtures/investigations/`

- [ ] **Step 1: Write failing transition and evidence tests**

Cover normal forward transitions, block from every active phase, resume only to
the recorded phase, complete only from verifying, and terminal completion. The
ledger must require distinct records for task classification, retrieved KB
resources and freshness, system entrypoint/readers/writers/downstream consumers,
blast radius, hypotheses, supporting evidence, contradicting evidence,
disconfirmation tests, and alternative dispositions.

- [ ] **Step 2: Write failing fix-gate tests**

Reject fixing without root cause plus failing test or executable reproduction.
Reject complete without reproduction, causal chain, affected cases,
verification results, and remaining uncertainty. Reject `root-caused` while any
hypothesis consistent with the symptom lacks a disconfirmation result or an
explicit unresolved disposition. A blocker is a valid task outcome but never
successful completion.

- [ ] **Step 3: Implement ledger commands and JSON summaries**

`kb bug status --json` must be suitable for Stop hooks and never require model
interpretation. It must expose booleans for every phase and evidence class so
hooks can reject incomplete ledgers deterministically.

- [ ] **Step 4: Integrate durable-learning proposal capture**

Completion should report whether a failure-mode proposal is required, already
created, or explicitly not durable with a reason.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_investigations.py kb/tests/test_cli_contract.py -k 'investigations or bug' -q`

Expected: PASS, including missing-map, missing-disconfirmation, and blocked-task cases.

Commit: `git commit -m "Add evidence-gated bug investigations"`

### Task 10: Canonical Policy Fragments, Generated Adapters, and Skills

**Files:**
- Create: `configs/agents/fragments/critical-rules.md`
- Create: `configs/agents/fragments/global-context.md`
- Create: `configs/agents/skills/knowledge-management/SKILL.md`
- Create: `configs/agents/skills/bug-investigation/SKILL.md`
- Create: `scripts/render-agent-instructions`
- Modify: `configs/agents/common-knowledge.md`
- Modify generated: `configs/agents/CLAUDE.md`
- Modify generated: `configs/agents/AGENTS.md`
- Modify generated: `configs/agents/GEMINI.md`
- Modify: `tests/test_agent_instructions.sh`
- Create: `tests/test_agent_policy_render.sh`

- [ ] **Step 1: Write failing render and drift tests**

Assert adapters are deterministic, contain fragment hashes/source headers, keep
the critical kernel short, route to the correct KB, invoke relevant skills, and
contain no copied private memory.

- [ ] **Step 2: Write failing rule tests**

Check English/Hinglish, no Hindi, no em dash, no agent attribution, quality over
cost, KB as sole durable memory, approval-gated stable changes, and mandatory bug
reproduction.

- [ ] **Step 3: Implement renderer and skills**

The bug skill must call `kb bug`; the knowledge skill must start with
`kb context`, inspect freshness, and use proposals rather than direct stable
edits.

- [ ] **Step 4: Regenerate all adapters and verify no manual drift**

Run: `scripts/render-agent-instructions --check`

- [ ] **Step 5: Run tests and commit**

Run: `tests/test_agent_policy_render.sh && tests/test_agent_instructions.sh && scripts/render-agent-instructions --check`

Expected: PASS and zero generated-adapter drift.

Commit: `git commit -m "Generate shared agent knowledge policy"`

### Task 11: Claude Settings, Hooks, and Attribution Enforcement

**Files:**
- Create: `configs/agents/claude/settings.fragment.json`
- Create: `configs/agents/claude/hooks/eos-agent-hook`
- Create: `scripts/merge-agent-settings`
- Modify: `scripts/install-agent-instructions`
- Create: `tests/test_claude_hooks.sh`
- Modify: `tests/test_agent_instructions.sh`

- [ ] **Step 1: Write failing settings merge tests**

Use temporary HOME profiles. Preserve authentication and unrelated user keys,
set empty commit/PR attribution and `sessionUrl: false`, install all hook events,
and prove idempotence.

- [ ] **Step 2: Write failing hook-contract tests**

Fixture events must cover `InstructionsLoaded`, `SessionStart`, lexical
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `PostCompact`,
`Stop`, and `SessionEnd`. Assert fast JSON output, no network, no secret
environment dump, and actionable failures. `PreToolUse` must reject agent
co-author trailers and session-attribution injection in commit and PR commands.

- [ ] **Step 3: Implement one deterministic hook dispatcher**

Delegate state to `kb`. Stop allows success only with a checkpoint and any
required completed investigation; it allows a recorded blocker as blocked work.
When lexical or transcript classification says the task was a bug but no ledger
exists, Stop must reject success and require `kb bug start`. Before allowing a
final response, reject the em dash code point and characters in Hindi Unicode
blocks, returning a correction request instead of rewriting the response.

- [ ] **Step 4: Add system-prompt launch support**

Claude wrappers must pass `critical-rules.md` with
`--append-system-prompt-file`. Keep detailed workflows in installed skills.

- [ ] **Step 5: Run tests and commit**

Run: `tests/test_claude_hooks.sh && tests/test_agent_instructions.sh`

Expected: PASS for every hook fixture, attribution denial, transcript bypass
attempt, em dash response, and Hindi response.

Commit: `git commit -m "Enforce Claude knowledge lifecycle hooks"`

### Task 12: Shared Agent Wrappers and Editor/Terminal Routing

**Files:**
- Create: `scripts/lib-agent-session.sh`
- Create: `scripts/claude-default`
- Create: `scripts/codex-default`
- Create: `scripts/claude-work`
- Create: `scripts/gemini-eos`
- Modify: `scripts/claude-personal`
- Modify: `scripts/codex-work`
- Modify: `scripts/codex-personal`
- Modify: `scripts/antigravity-full`
- Modify: `scripts/backend`
- Modify: `scripts/research`
- Modify: `scripts/agents`
- Modify: `configs/wezterm/launch.lua`
- Modify: `configs/nvim/lua/config/eos_keymaps.lua`
- Create: `tests/test_agent_sessions.sh`
- Modify: `tests/test_workspace_scripts.sh`
- Modify: `tests/test_nvim_keymaps.sh`

- [ ] **Step 1: Write failing dry-run routing tests**

Assert every launch path calls a wrapper, runs doctor, starts one session,
selects default, work, or personal profile through the explicit wrapper and cwd,
includes KB write access, runs `kb audit` before agent launch, and ends the same
session while preserving the agent exit code. Cover default Claude and Codex
profiles, not only work and personal profiles.

- [ ] **Step 2: Write signal and missing-KB tests**

TERM/INT should checkpoint when possible. KILL must be recoverable next start.
Missing or non-writable KB must fail before launching the agent with remediation.

- [ ] **Step 3: Implement shared lifecycle without `exec` before cleanup**

Use a shell trap for normal exits and signals. Pass native session IDs when the
agent exposes one; otherwise use EOS UUIDs. The shared start path must audit
before `kb session start`; checkpoint and end paths must audit again.

- [ ] **Step 4: Replace all direct Claude/Codex commands**

WezTerm, tmux workspace commands, and Neovim must call the same wrappers so
profile routing and hooks cannot diverge.

`install-agent-instructions` must install policy and skills into default, work,
and personal Claude/Codex profiles, Gemini CLI skill directories, and both
`~/.gemini/antigravity-ide/skills` and Antigravity CLI/config skill directories.
Tests must use temporary HOME and enumerate every destination.

- [ ] **Step 5: Run tests and commit**

Run: `tests/test_agent_sessions.sh && tests/test_workspace_scripts.sh && tests/test_nvim_keymaps.sh && tests/test_agent_instructions.sh`

Expected: PASS for all default/work/personal dry runs and installation targets.

Commit: `git commit -m "Route all agents through EOS sessions"`

### Task 13: Migration Planner, Apply, Backup, and Rollback

**Files:**
- Create: `kb/src/eos_kb/migration.py`
- Create: `configs/kb/schemas/migration-v1.json`
- Create: `configs/kb/migration-scopes.yaml`
- Create: `kb/tests/test_migration.py`
- Create: `kb/tests/fixtures/legacy-work-kb/`
- Create: `kb/tests/fixtures/legacy-personal-kb/`

- [ ] **Step 1: Write failing inventory and inference tests**

Manifest entries must include source path/hash, target path, inferred type,
planned metadata, permissions, and action. Inference may use path and title only
and must not synthesize descriptions or claims.

Define ordered work scopes by path glob. `high-value-nova` contains the work root
routers, `areas/coding-guidelines.md`, `areas/vikas-agent-profile.md`, `patterns/**`,
and non-log/non-archive `projects/backend-project/**`. `remaining` is the explicit
set difference between the complete inventory and every prior scope. Personal
uses one `all` scope. Planning must reject overlaps, unmatched inventory entries,
and any scope definition that changes after manifest creation.

- [ ] **Step 2: Write failing apply-precondition tests**

Reject apply when the manifest hash, any source hash, or registry changed. Keep
legacy `00-index.md` and pending entrypoints. Preserve unknown files.

- [ ] **Step 3: Write failing backup and rollback tests**

Simulate interruption during apply, verify exact path/permission restoration,
and ensure rollback never deletes files absent from the manifest.

- [ ] **Step 4: Implement `migrate inventory|plan|verify-plan|apply|rollback`**

Default to dry-run. `apply` requires `--manifest`, `--manifest-hash`,
`--approved-by`, and `--approval-session`. `plan --scope <name>` must produce an
independent content-addressed manifest containing only that declared batch.
`verify-plan` recomputes manifest, source, registry, and scope hashes plus action
counts without writing live files. Multiple batches require separately approved
manifest hashes. A later batch must be planned only after the previous batch has
been applied and re-indexed; tests must prove a preplanned later manifest becomes
invalid after an earlier batch changes shared routers or manifests.

`apply` also requires `--receipt-out <path>`. Before its first live mutation it
writes that receipt atomically with transaction ID, KB root, manifest path/hash,
backup root, original hashes/permissions, and `in_progress` state; success changes
the state to `applied`. `rollback` requires `--kb`, `--manifest`,
`--manifest-hash`, and `--receipt`. It verifies all receipt and backup hashes,
accepts both `in_progress` and `applied`, restores only manifest-owned paths, and
marks the receipt `rolled_back`. This same command recovers an interrupted apply.

- [ ] **Step 5: Run fixture migrations twice and commit**

Run: `uv run --project kb pytest kb/tests/test_migration.py kb/tests/test_cli_contract.py -k 'migration or migrate' -q`

Expected: PASS for full and scoped manifests, changed-plan rejection, interrupted
apply, and exact rollback.

Commit: `git commit -m "Add lossless knowledge migration tooling"`

### Task 14: Bootstrap, Doctor, and Live Installation Contracts

**Files:**
- Modify: `scripts/eos`
- Modify: `bootstrap/bootstrap.sh`
- Modify: `bootstrap/verify.sh`
- Modify: `tests/test_paths.sh`
- Modify: `tests/test_symlinks.sh`
- Create: `tests/test_kb_doctor.sh`
- Create: `configs/launchd/com.vikas.eos-kb-audit.plist.in`
- Create: `scripts/kb-audit-all`
- Create: `scripts/install-kb-audit`
- Create: `tests/test_kb_audit_schedule.sh`
- Modify: `INSTALL.md`
- Modify: `TESTING.md`

- [ ] **Step 1: Write failing doctor and bootstrap tests with temporary HOME**

Check runtime version, FTS5, registry, KB readability/writeability, schema
version, index health, hooks, policy hashes, profile skills, and stale sessions.

- [ ] **Step 2: Implement idempotent bootstrap ordering**

Order: provision runtime, scaffold missing KBs, render policy, install adapters
and skills, merge settings, install wrappers, install the periodic audit
LaunchAgent, run doctor. Back up before replacing non-symlink files. The
LaunchAgent runs work and personal `kb audit` every six hours and at login,
writes only derived state/logs, and uses no network.

`scripts/kb-audit-all` resolves absolute EOS and KB roots from `HOME` plus
supported environment overrides, invokes `scripts/kb audit --kb <root>` once for
work and once for personal, always attempts both, writes separate state/log keys,
and exits nonzero if either audit fails. `install-kb-audit` renders the `.plist.in`
placeholders to absolute paths under `~/Library/LaunchAgents`, sets
`ProgramArguments` to `/bin/zsh`, the absolute runner, and no shell interpolation,
sets `RunAtLoad=true` and `StartInterval=21600`, validates with `plutil`, then
bootstraps the user LaunchAgent. Temporary-HOME tests inspect the rendered plist
and execute the runner with a fake `kb` binary.

- [ ] **Step 3: Add `eos kb ...` and `eos agent doctor` routing**

Keep `scripts/eos` thin and forward all KB behavior to `scripts/kb`.

- [ ] **Step 4: Run isolated bootstrap twice**

Expected: second run changes no generated file hashes and makes no additional
backup for unchanged content.

- [ ] **Step 5: Run tests and commit**

Run: `tests/test_kb_doctor.sh && tests/test_kb_audit_schedule.sh && tests/test_paths.sh && tests/test_symlinks.sh`

Expected: PASS in temporary HOME, including two idempotent bootstrap runs and a
synthetic scheduled-audit invocation.

Commit: `git commit -m "Install and diagnose the knowledge system"`

### Task 15: Retrieval Benchmarks and Cross-Agent Adherence Harness

**Files:**
- Create: `kb/tests/fixtures/benchmark/queries.yaml`
- Create: `kb/tests/test_benchmark.py`
- Create: `tests/test_agent_adherence.sh`
- Create: `tests/fixtures/agent-adherence/`
- Create: `configs/agents/adherence-matrix.yaml`
- Modify: `bootstrap/verify.sh`

- [ ] **Step 1: Add 15 to 25 work project fixture queries with expected resources**

Include exact identifiers, paths, flags, error strings, conceptual symptoms,
stale concepts, contradictions, and history-only queries. Fixture content must
be synthetic or locally redacted.

- [ ] **Step 2: Implement deterministic benchmark assertions**

Require 100 percent Recall@5 for exact queries, at least 90 percent overall,
100 percent warning recall, median at most 1,500 EOS units, and no 2,500-unit
budget overflow. Also calculate and report Precision@5 and
query execution latency. Retrieval tests do not claim to measure hypothesis
formation because the deterministic retrieval engine does not produce hypotheses.

- [ ] **Step 3: Implement deterministic profile adherence checks**

Check installed files, hooks, wrappers, routing, attribution settings, no em dash,
no Hindi, and required skills for every supported profile.

- [ ] **Step 4: Add opt-in behavioral trials**

`EOS_RUN_AGENT_BEHAVIOR_TESTS=1` runs at least three isolated trials per installed
profile, records no private repo content, and enforces 90 percent overall with no
profile below 80 percent. Deterministic checks always run.

`configs/agents/adherence-matrix.yaml` enumerates Claude default/work/personal,
Codex default/work/personal, Gemini CLI, Antigravity CLI, and Antigravity IDE.
Every profile must run all matrix rows: fresh session, resume, compaction,
subagent, work routing, personal routing, bug task/reproduction gate, KB-impacting
task/proposal gate, commit attribution, and language/punctuation. This produces
ten trials per profile, exceeding the three-trial minimum. A missing transport or
unsupported row is a failure, not a skip, for rollout acceptance.

The bug-task row measures time-to-first-correct-hypothesis. Each synthetic prompt
provides neutral candidate IDs with hypothesis descriptions but keeps
`expected_hypothesis_ids` hidden in the harness fixture. The harness starts a
monotonic timer at prompt submission, requires machine-readable
`HYPOTHESIS <candidate-id>` transcript events, and records the first event whose
public candidate ID is in the hidden expected set. No matching event is an
incorrect trial. The value is reported for diagnosis but has no initial pass
threshold.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --project kb pytest kb/tests/test_benchmark.py -q && tests/test_agent_adherence.sh`

Expected: PASS for all deterministic thresholds. Behavioral trials print a
clear skipped status unless explicitly enabled.

Commit: `git commit -m "Add knowledge and agent adherence benchmarks"`

### Task 16: Live Migration, Rollout, Documentation, and Final Verification

**Files:**
- Create: `docs/AGENT_KNOWLEDGE_SYSTEM.md`
- Modify: `docs/AGENT_KNOWLEDGE.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify after approval: `$HOME/personal/knowledge/**`
- Modify after approval: `$HOME/work/knowledge/**`
- Rename during rollout: `$HOME/work/backend-project/.claude/claude.md`
  to `$HOME/work/backend-project/.claude/CLAUDE.md`
- Modify during rollout: `$HOME/work/backend-project/CLAUDE.md`

- [ ] **Step 1: Plan the personal migration without changing the KB**

Run:

```bash
kb migrate plan --kb ~/personal/knowledge --output /tmp/personal-kb-migration.json
PERSONAL_HASH="$(kb migrate verify-plan /tmp/personal-kb-migration.json --print-hash)"
```

Record hashes, counts by action/type, conflicts, unknowns, and backup locations.

- [ ] **Step 2: Stop and obtain explicit approval for the personal manifest hash**

Do not treat approval of this implementation plan as approval of a later
generated manifest. If the manifest changes, obtain approval again.

- [ ] **Step 3: Apply personal first, validate, and exercise retrieval**

Apply the approved personal manifest, run strict validation, index, benchmark
personal exact routes, and verify legacy `00-index.md` compatibility. Roll back
immediately on any structural or content mismatch.

```bash
kb migrate apply --kb ~/personal/knowledge --manifest /tmp/personal-kb-migration.json --manifest-hash "$PERSONAL_HASH" --approved-by Vikas --approval-session "$PERSONAL_APPROVAL_SESSION" --receipt-out /tmp/personal-kb-migration.receipt.json
kb validate --strict --kb ~/personal/knowledge
```

If apply is interrupted or any validation fails, run exactly:

```bash
kb migrate rollback --kb ~/personal/knowledge --manifest /tmp/personal-kb-migration.json --manifest-hash "$PERSONAL_HASH" --receipt /tmp/personal-kb-migration.receipt.json
```

- [ ] **Step 4: Plan and approve the high-value work project batch**

Run after personal validation:

```bash
kb migrate plan --kb ~/work/knowledge --scope high-value-nova --output /tmp/work-kb-nova-migration.json
NOVA_HASH="$(kb migrate verify-plan /tmp/work-kb-nova-migration.json --print-hash)"
```

Stop and obtain explicit approval for this exact manifest hash.

- [ ] **Step 5: Apply and validate the high-value work project batch**

Apply only the approved `high-value-nova` manifest, then strict-validate,
re-index, and audit the work KB. This establishes the baseline for the next plan.

```bash
kb migrate apply --kb ~/work/knowledge --manifest /tmp/work-kb-nova-migration.json --manifest-hash "$NOVA_HASH" --approved-by Vikas --approval-session "$NOVA_APPROVAL_SESSION" --receipt-out /tmp/work-kb-nova-migration.receipt.json
kb validate --strict --kb ~/work/knowledge
```

On interruption or validation failure:

```bash
kb migrate rollback --kb ~/work/knowledge --manifest /tmp/work-kb-nova-migration.json --manifest-hash "$NOVA_HASH" --receipt /tmp/work-kb-nova-migration.receipt.json
```

- [ ] **Step 6: Plan and approve the remaining work batch from the new baseline**

Run only after Step 5 succeeds:

```bash
kb migrate plan --kb ~/work/knowledge --scope remaining --output /tmp/work-kb-remaining-migration.json
REMAINING_HASH="$(kb migrate verify-plan /tmp/work-kb-remaining-migration.json --print-hash)"
```

Stop and obtain explicit approval for this exact post-batch manifest hash.

- [ ] **Step 7: Apply and validate the remaining work batch**

Apply only the approved `remaining` manifest, then strict-validate, re-index, and
audit. Do not delete or split legacy content without a separately approved
proposal.

```bash
kb migrate apply --kb ~/work/knowledge --manifest /tmp/work-kb-remaining-migration.json --manifest-hash "$REMAINING_HASH" --approved-by Vikas --approval-session "$REMAINING_APPROVAL_SESSION" --receipt-out /tmp/work-kb-remaining-migration.receipt.json
kb validate --strict --kb ~/work/knowledge
```

On interruption or validation failure:

```bash
kb migrate rollback --kb ~/work/knowledge --manifest /tmp/work-kb-remaining-migration.json --manifest-hash "$REMAINING_HASH" --receipt /tmp/work-kb-remaining-migration.receipt.json
```

- [ ] **Step 8: Harden work project repository instruction loading in its own commit**

Check work project status first and stage only the two instruction paths. On the default
case-insensitive macOS filesystem, perform a two-step rename:

```bash
git -C ~/work/backend-project mv .claude/claude.md .claude/CLAUDE.tmp
git -C ~/work/backend-project mv .claude/CLAUDE.tmp .claude/CLAUDE.md
```

Replace the root CLAUDE.md Markdown link with exact `@AGENTS.md` import syntax,
verify Claude loads both instruction files in an isolated work project session, then
commit these work project-only changes without an agent co-author.

- [ ] **Step 9: Install agent integrations into live profiles**

Run bootstrap with backups. Verify Claude, Codex, Gemini, and Antigravity work
and personal launches, KB write access, session start/end, killed-session
recovery, attribution settings, periodic audit, and every adherence-matrix
transport.

- [ ] **Step 10: Run full verification**

```bash
uv run --project kb pytest kb/tests -q
for test_file in tests/test_*.sh; do "$test_file"; done
EOS_RUN_AGENT_BEHAVIOR_TESTS=1 tests/test_agent_adherence.sh
scripts/render-agent-instructions --check
kb validate --strict --kb ~/personal/knowledge
kb validate --strict --kb ~/work/knowledge
kb audit --kb ~/personal/knowledge
kb audit --kb ~/work/knowledge
bootstrap/verify.sh
git diff --check
```

Expected: zero failures, zero invalid stable concepts, no hard budget overflow,
and only explicitly acknowledged stale/unknown warnings.

- [ ] **Step 11: Update docs and commit rollout artifacts**

Document daily search, context, proposal review, direct-change review, session
recovery, bug ledger, migration rollback, and troubleshooting. Never commit
private KB content into EOS.

Commit: `git commit -m "Roll out the EOS agent knowledge system"`

---

## Execution Rules

- Use `superpowers:test-driven-development` for every runtime or behavior task.
- Use `superpowers:systematic-debugging` for every unexpected test or E2E result.
- Use `superpowers:verification-before-completion` before each commit and phase
  claim.
- Keep each task's commit isolated. Never stage unrelated changes.
- Never add an agent as commit or PR co-author.
- Never edit curated stable KB content outside the approved migration or proposal
  paths.
- Do not push the implementation branch until the complete deterministic test
  suite passes.
