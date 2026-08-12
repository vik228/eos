# EOS Personal KB Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every EOS coding-agent session to durable EOS project knowledge in the personal KB while preserving research project isolation and verified write access.

**Architecture:** Resolve workspace identity from cwd before accepting a shared explicit KB root. Provision a lightweight EOS project route through the reproducible personal scaffold, render an explicit EOS startup instruction into every agent profile, and keep live KB updates governed. Repository docs remain authoritative; the KB stores durable routing and collaboration context only.

**Tech Stack:** Python 3.12, pytest, Bash, YAML, Markdown, EOS KB governance CLI, Claude/Codex/Gemini/Antigravity profile renderers.

---

### Task 1: Make Shared-KB Routing Cwd-First

**Files:**
- Modify: `kb/src/eos_kb/config.py`
- Modify: `kb/tests/test_config.py`
- Modify: `kb/tests/test_retrieval.py`

- [ ] **Step 1: Add failing resolver tests**

Create two registered workspaces that share one KB and assert:

```python
eos = resolve_workspace(eos_cwd / "scripts", registry=registry, kb=shared_kb)
genesis = resolve_workspace(genesis_cwd / "notebooks", registry=registry, kb=shared_kb)
assert eos.project == "eos"
assert genesis.project == "nlp-to-llm-evolution"
```

Also assert an explicit KB conflicting with a matched cwd raises
`registry.kb_mismatch`, while an unregistered cwd plus explicit KB returns an
unregistered route with project `knowledge`.

Add a parent and nested registered workspace that share the explicit KB. Resolve
from inside the nested workspace and assert longest-prefix selection preserves
the nested project and coverage. Repeat with a conflicting KB and assert the
mismatch is checked against the nested route.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
EOS_KB_STATE_ROOT=/tmp/eos-kb-route-red PYTHONPATH=kb/src \
  python3 -m pytest kb/tests/test_config.py kb/tests/test_retrieval.py -q
```

Expected: shared-KB project selection and mismatch tests fail under the current
first-KB-match behavior.

- [ ] **Step 3: Implement cwd-first explicit-KB resolution**

In `resolve_workspace`:

1. Normalize the explicit KB.
2. Attempt `match_workspace(cwd, registry)`.
3. If cwd is registered, reject a different explicit KB and preserve that cwd
   route's project and coverage.
4. If cwd is unregistered, return an unregistered route for the explicit KB and
   do not infer a project from another workspace sharing that KB.
5. Preserve explicit non-empty project overrides.

- [ ] **Step 4: Run focused and full Python tests**

Run:

```bash
EOS_KB_STATE_ROOT=/tmp/eos-kb-route-green PYTHONPATH=kb/src \
  python3 -m pytest kb/tests/test_config.py kb/tests/test_retrieval.py -q
EOS_KB_STATE_ROOT=/tmp/eos-kb-route-suite PYTHONPATH=kb/src \
  python3 -m pytest kb/tests -q
```

Expected: PASS with no new skips.

- [ ] **Step 5: Commit**

```bash
git add kb/src/eos_kb/config.py kb/tests/test_config.py kb/tests/test_retrieval.py
git commit -m "Fix shared personal KB workspace routing"
```

### Task 2: Add the Reproducible EOS Personal-KB Scaffold

**Files:**
- Create: `personal-knowledge/projects/eos/00-index.md`
- Create: `personal-knowledge/projects/eos/_pending-kb-updates.md`
- Modify: `personal-knowledge/00-index.md`
- Modify: `personal-knowledge/_pending-kb-updates.md`
- Modify: `scripts/install-personal-knowledge-indexes`
- Modify: `tests/test_personal_knowledge_indexes.sh`
- Modify: `tests/test_bootstrap_idempotence.sh`

- [ ] **Step 1: Add failing scaffold and installer assertions**

Require the EOS project files, root-router links, project pending-queue link, and
installer destinations. Add isolated install tests proving:

- missing project files are installed;
- a second run is unchanged;
- user-modified targets are preserved without `--force`;
- forced replacement creates a backup before writing.

- [ ] **Step 2: Run the shell tests and confirm RED**

```bash
tests/test_personal_knowledge_indexes.sh
tests/test_bootstrap_idempotence.sh
```

Expected: FAIL because the EOS scaffold and installer routes do not exist.

- [ ] **Step 3: Create the lightweight authored routes**

Use canonical `00-index.md` files with valid frontmatter. The EOS project index
must contain only:

- workspace and KB route;
- durable collaboration invariants;
- resume procedure;
- authoritative repo paths for `docs/AGENT_KNOWLEDGE_SYSTEM.md`,
  `docs/AGENT_KNOWLEDGE.md`, `docs/PRODUCTIVITY.md`, and
  `bootstrap/verify.sh`;
- a pointer to `_pending-kb-updates.md`.

Do not copy mutable versions, test counts, rollout status, receipts, or source
documentation into the KB scaffold.

- [ ] **Step 4: Extend the installer without overwriting existing content**

Create `projects/eos`, then call the existing `install_index` helper for both EOS
project files. Preserve the current default and forced-backup semantics.

- [ ] **Step 5: Run the focused shell tests**

Run the two commands from Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add personal-knowledge scripts/install-personal-knowledge-indexes \
  tests/test_personal_knowledge_indexes.sh tests/test_bootstrap_idempotence.sh
git commit -m "Add reproducible EOS personal KB scaffold"
```

### Task 3: Register EOS and Render Route-Aware Agent Instructions

**Files:**
- Modify: `configs/kb/workspaces.yaml`
- Modify: `configs/agents/common-knowledge.md`
- Modify generated: `configs/agents/AGENTS.md`
- Modify generated: `configs/agents/CLAUDE.md`
- Modify generated: `configs/agents/GEMINI.md`
- Modify: `scripts/render-agent-instructions`
- Modify: `scripts/install-agent-instructions`
- Modify: `kb/tests/test_config.py`
- Modify: `tests/test_agent_instructions.sh`
- Modify: `tests/test_agent_policy_render.sh`
- Modify: `tests/test_symlinks.sh`

- [ ] **Step 1: Add failing registry and rendered-profile tests**

Require `~/personal/eos` to resolve to the personal KB with project `eos`.
Require every rendered Claude, Codex, and Gemini instruction file to state that
sessions inside `$HOME/personal/eos` read the personal root index
and `projects/eos/00-index.md` before changing code.

Antigravity uses the same global rule at `~/.gemini/GEMINI.md` as Gemini. Add
explicit installer and transport assertions proving both Antigravity CLI and IDE
profiles consume the generated `configs/agents/GEMINI.md`; do not introduce a
second divergent Antigravity policy file.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
EOS_KB_STATE_ROOT=/tmp/eos-kb-registry-red PYTHONPATH=kb/src \
  python3 -m pytest kb/tests/test_config.py -q
tests/test_agent_instructions.sh
tests/test_agent_policy_render.sh
tests/test_symlinks.sh
```

- [ ] **Step 3: Add the registry route and global instruction**

Add:

```yaml
~/personal/eos:
  kb: ~/personal/knowledge
  project: eos
```

Add one EOS-specific route instruction to `common-knowledge.md`, then run:

```bash
scripts/render-agent-instructions
```

- [ ] **Step 4: Verify rendered profiles and registry tests**

Run the commands from Step 2, `scripts/render-agent-instructions --check`, and a
deterministic Antigravity adherence transport trial. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add configs/kb/workspaces.yaml configs/agents scripts/render-agent-instructions \
  scripts/install-agent-instructions tests/test_agent_instructions.sh \
  tests/test_agent_policy_render.sh tests/test_symlinks.sh kb/tests/test_config.py
git commit -m "Route EOS agent sessions to personal knowledge"
```

### Task 4: Enforce and Test Codex Personal Dual-Write Preconditions

**Files:**
- Modify: `scripts/lib-agent-session.sh`
- Create: `tests/test_codex_personal_writes.sh`
- Modify: `bootstrap/verify.sh`

- [ ] **Step 1: Write failing E2E launcher tests**

Use a fake Codex executable and isolated HOME. Launch `scripts/codex-personal`
with temporary EOS workspace and KB roots. The fake executable must parse the
launcher arguments and write one marker under each supplied root. Assert both
writes succeed and the launch includes the personal `CODEX_HOME`, cwd, KB
`--add-dir`, configured sandbox, network access, and no-approval mode.

Add negative cases for missing/non-writable workspace and KB roots. Assert the
agent executable is never called.

- [ ] **Step 2: Run the new E2E test and confirm RED**

```bash
tests/test_codex_personal_writes.sh
```

Expected: workspace non-writable precondition is not enforced.

- [ ] **Step 3: Add workspace writability preflight**

In `agent_session_run`, require both `cwd` and `kb_root` to exist as writable
directories before doctor, audit, session start, or agent launch.

- [ ] **Step 4: Run E2E and existing session tests**

```bash
tests/test_codex_personal_writes.sh
tests/test_agent_sessions.sh
tests/test_workspace_scripts.sh
```

Expected: PASS.

- [ ] **Step 5: Register the check in bootstrap verification and commit**

```bash
git add scripts/lib-agent-session.sh tests/test_codex_personal_writes.sh bootstrap/verify.sh
git commit -m "Verify Codex personal workspace and KB writes"
```

### Task 5: Install Runtime Changes and Promote the Live EOS KB Route

**Files:**
- Live governed targets: `$HOME/personal/knowledge/00-index.md`
- Live governed targets: `$HOME/personal/knowledge/_pending-kb-updates.md`
- Live governed targets: `$HOME/personal/knowledge/projects/eos/00-index.md`
- Live governed targets: `$HOME/personal/knowledge/projects/eos/_pending-kb-updates.md`

- [ ] **Step 1: Install the updated KB runtime and agent instructions**

```bash
scripts/setup-kb
scripts/install-agent-instructions
```

- [ ] **Step 2: Start a governed EOS personal-KB session**

```bash
scripts/kb session start --kb ~/personal/knowledge --cwd ~/personal/eos \
  --agent codex --profile personal --json
```

Assert the route resolves project `eos`, not `nlp-to-llm-evolution`.

- [ ] **Step 3: Create exact live proposals**

Prepare proposal files from the approved scaffold while preserving existing
research project links in both live root routers. Create four proposals with `kb propose`:

1. EOS project index;
2. EOS pending queue;
3. personal root index with EOS link;
4. personal pending root with EOS queue link.

- [ ] **Step 4: Stop for exact proposal review**

Show Vikas each captured proposal ID, target, and exact content diff. Stop and
obtain explicit acceptance for those exact proposals. Design or plan approval is
not proposal approval, and must not be recorded as one.

- [ ] **Step 5: Record exact decisions and promote accepted proposals**

After Vikas explicitly accepts the proposal set, record each decision with
`kb review`, then promote only accepted proposal IDs through `kb promote`. Do not
direct-edit live KB files or synthesize an approval actor.

- [ ] **Step 6: Re-index and strictly validate**

```bash
scripts/kb index --kb ~/personal/knowledge
scripts/kb validate --strict --kb ~/personal/knowledge
scripts/kb status --kb ~/personal/knowledge
```

Expected: ready index, zero validation errors, research project and EOS project routes
both present.

### Task 6: Fresh-Session E2E and Full Verification

**Files:**
- Modify only if verification exposes a tested defect.

- [ ] **Step 1: Verify route isolation from both workspaces**

Run `kb context` and `kb search` from EOS and research project cwd values while passing the
same personal `--kb`. Assert EOS results are project `eos` scoped and research project
results are `nlp-to-llm-evolution` scoped.

- [ ] **Step 2: Exercise a fresh Codex personal dry-run and fake-agent launch**

Assert the EOS cwd, writable KB root, route-aware global instruction, session
start/checkpoint/end transport, and MCP/profile settings are present.

- [ ] **Step 3: Run deterministic verification**

```bash
EOS_KB_STATE_ROOT=/tmp/eos-kb-final PYTHONPATH=kb/src python3 -m pytest kb/tests -q
for test_file in tests/test_*.sh; do "$test_file"; done
scripts/render-agent-instructions --check
scripts/kb validate --strict --kb ~/personal/knowledge
bootstrap/verify.sh
git diff --check
git status -sb
```

Expected: zero failures, strict KB validation passes, bootstrap status is 0,
and only explicitly preserved unrelated files appear in status.

- [ ] **Step 4: Commit and push any final tested corrections**

Push EOS `main`, confirm `HEAD == origin/main`, and report the live verification
evidence and whether profile restart is required.
