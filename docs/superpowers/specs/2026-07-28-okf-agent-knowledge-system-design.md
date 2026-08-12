# EOS Agent Knowledge System Design

Date: 2026-07-28
Status: Approved design, pending implementation planning

## 1. Objective

Build a reproducible, agent-neutral knowledge system in EOS that:

- Organizes work and personal knowledge as OKF-compatible Markdown bundles.
- Lets agents retrieve relevant knowledge with a small, bounded token budget.
- Detects stale, contradictory, orphaned, and uncovered knowledge mechanically.
- Captures evidence and proposals automatically, while keeping promotion into
  stable knowledge approval-gated.
- Gives Claude, Codex, Gemini, and Antigravity the same knowledge-management
  and bug-investigation behavior.
- Converts critical global instructions from advisory prose into the strongest
  available combination of system-prompt rules, skills, settings, hooks, and
  deterministic validators.
- Requires evidence-led E2E reproduction and hypothesis testing before an agent
  implements a bug fix.

Markdown remains the source of truth. Search indexes, session state, and
freshness calculations are disposable derived data.

## 2. Current-State Findings

The current system already has useful foundations:

- Separate work and personal knowledge roots.
- Root and project routers using `00-index.md`.
- Global agent instructions installed into dedicated profiles.
- Claude proposal-only knowledge hooks for work project and research project.
- Codex work-session capture around the work project repository.

The main limitations are:

- The work KB has 142 Markdown files and roughly 243,000 words, but only three
  index files.
- The work project project index is roughly 3,461 words and mixes routing with detailed
  status, history, and conclusions.
- Work KB concept documents do not carry OKF frontmatter.
- Several documents are 10,000 to 21,000 words, so opening a whole file is an
  expensive retrieval operation.
- Logs, proposals, current truth, specifications, historical incidents, and
  archived material are not consistently separated during search.
- SessionEnd capture is not sufficient when a process is killed or an agent
  simply forgets to update knowledge.
- Global instructions are loaded by Claude, but CLAUDE.md is advisory context,
  not deterministic configuration.
- Claude commit attribution remains enabled because the user settings do not
  explicitly disable it.
- work project's detailed project file is named `.claude/claude.md` rather than the
  portable `.claude/CLAUDE.md`, and the root CLAUDE.md links to AGENTS.md using
  a Markdown link instead of Claude's `@AGENTS.md` import syntax.

## 3. Locked Decisions

1. Cover both work and personal KBs.
2. Use OKF-compatible Markdown as the canonical storage format.
3. Use a local deterministic retrieval engine backed by SQLite FTS5.
4. Do not add vector embeddings or a long-running MCP service in the first
   implementation.
5. Provide one `kb` CLI used by every agent. An MCP adapter may be added later
   without changing storage or command semantics.
6. Use hybrid governance:
   - Evidence, logs, proposals, indexes, and derived state may update
     automatically.
   - Stable knowledge changes, invariant changes, and deprecations require
     explicit user approval.
7. Do not rely on agents remembering to maintain the KB. Run deterministic
   freshness checks at startup, checkpoint, exit, and periodic audit.
8. Do not rely on one large global instruction file. Split global behavior into
   a small critical kernel, task-triggered skills, deterministic settings, and
   hooks.
9. Keep repository-owned rules in their repositories. The KB links to them and
   complements them without copying their content.

## 4. System Boundaries

The program contains six independently testable components:

1. **Bundle model**: OKF-compatible Markdown conventions and validation.
2. **Retrieval engine**: indexing, ranking, bounded context assembly, and links.
3. **Freshness engine**: source drift, time drift, contradictions, and coverage.
4. **Governance engine**: proposal capture, review, promotion, and deprecation.
5. **Agent integration**: profiles, skills, wrappers, hooks, and global policy.
6. **Bug investigation**: evidence ledger and fix/verification gates.

Each component exposes a CLI contract through `kb`; agents do not depend on
internal Python APIs or SQLite schema details.

## 5. Bundle Structure

Work and personal knowledge use the same layout:

```text
knowledge/
|-- index.md
|-- 00-index.md
|-- _pending-kb-updates.md
|-- areas/
|-- patterns/
|-- projects/
|   `-- <project>/
|       |-- index.md
|       |-- architecture/
|       |-- invariants/
|       |-- decisions/
|       |-- runbooks/
|       |-- failure-modes/
|       |-- incidents/
|       |-- specifications/
|       `-- references/
|-- logs/
|-- inbox/
`-- archive/
```

`index.md` is the canonical OKF router. `00-index.md` remains a compact legacy
router during migration and links to `index.md`. It is represented as a valid
OKF concept rather than as duplicated knowledge.

`_pending-kb-updates.md` remains as a compatibility entrypoint, but becomes a
small proposal-queue concept linking to project-specific inbox indexes.

Content classes have different default retrieval behavior:

- Stable: architecture, invariants, accepted decisions, runbooks, patterns.
- Diagnostic: failure modes and verified incidents.
- Work in progress: specifications with `status: draft`.
- Excluded by default: logs, inbox proposals, archive, deprecated concepts.

Lifecycle, trust, type, freshness, and authority are separate dimensions. Their
canonical mapping is:

| Dimension | Values | Effect |
|---|---|---|
| `status` | `draft`, `stable`, `deprecated` | OKF lifecycle; absent means `stable` |
| trust tier | unverified, machine-confirmed, human-reviewed | Derived from verification evidence and approval records |
| freshness | fresh, stale, unknown | Derived from sources and `stale_after` |
| type | Any non-empty string | Controls default search inclusion, never lifecycle |
| authoritative | true or false | Derived, never stored |

A concept is authoritative only when it is `stable`, fresh, human-reviewed, and
not generated.
Stable unverified concepts remain searchable but are labeled unverified. Draft,
Session Log, and Knowledge Proposal concepts are excluded unless requested.
Deprecated concepts are excluded unless requested or reached through a
supersession/history query. A stale concept remains visible when relevant but is
never presented without a warning. These rules take precedence over directory
names and filename conventions.

Trust derivation is deterministic:

- `unverified`: no valid verification evidence exists for the current concept
  hash.
- `machine-confirmed`: `verified` records a successful automated check and the
  generated manifest binds that evidence to the current concept hash, but no
  human acceptance record matches that hash.
- `human-reviewed`: `.eos/approvals.jsonl` contains an accepted review record
  matching the current concept hash.

The OKF `verified` field records verification evidence. It is not itself human
authorization and cannot bypass the EOS approval log.

## 6. Metadata Model

Every non-reserved concept document gets YAML frontmatter. Only `type` is
required by OKF. EOS recommends additional fields only when they improve
retrieval, trust, or freshness.

Standard OKF v0.2 fields used by EOS:

- `type`
- `title`
- `description`
- `resource`
- `tags`
- `generated`
- `verified`
- `sources`
- `status`
- `stale_after`

EOS-specific metadata is namespaced to avoid collision with future OKF fields:

```yaml
eos:
  project: backend-project
  components: [identity, booking-family]
  symptoms: [incorrect-family-status, ui-state-mismatch]
  source_paths:
    - domains/execution/identity.py
  source_revision: 09536c6
  owner: team:nova
  supersedes:
    - incidents/legacy-family-rollup.md
  claims:
    - id: booking-family.status-source
      value: latest-lifecycle-intent
```

All EOS extension fields are optional. Validators reject malformed values but
do not require metadata that is irrelevant to a concept.

`eos.claims` is optional, but required for deterministic contradiction checks.
Claim IDs are project-scoped stable identifiers. A contradiction exists only
when two non-deprecated concepts declare the same claim ID with different
normalized scalar or JSON values. Normalization parses YAML into JSON-compatible
values, rejects floating-point claim values, normalizes strings and object keys
to Unicode NFC, preserves array order, sorts object keys lexicographically, and
serializes compact UTF-8 JSON. Duplicate keys after normalization are rejected.
Integers use base-10 representation; booleans and null use JSON literals.
Prose-only disagreement may be surfaced as a search candidate, but EOS does not
claim to detect it deterministically.

`eos.source_paths` is optional globally, but required for deterministic source
drift and coverage guarantees. Project registry entries may additionally define
coverage rules:

```yaml
coverage:
  - paths: ["domains/execution/**/*.py"]
    concepts: ["kb:nova/architecture/execution"]
    ignore: ["**/__pycache__/**"]
```

`coverage.concepts` contains canonical concept `resource` identifiers resolved
through the index. For a changed path, a mapped concept is `current` only when
its generated manifest entry records the current Git blob hash. It is `pending`
when an active proposal targeting that resource records the current blob hash
and path. Otherwise it is `drifted`. The aggregate path state is `current` when
at least one mapped concept is current, `pending` when none is current but at
least one is pending, and `drifted` otherwise. Pending and drifted paths produce
search and checkpoint warnings. A path outside declared concept sources or
project coverage rules is explicitly reported as `coverage: unknown`, not
incorrectly treated as covered.

Each concept's `eos.source_paths` acts as an implicit coverage rule mapping those
paths to that concept's own canonical `resource`.

Initial controlled concept types include:

- Architecture
- Invariant
- Decision
- Runbook
- Pattern
- Failure Mode
- Incident
- Specification
- Reference
- Session Log
- Knowledge Proposal
- Router

Unknown types remain consumable, as required by OKF.

## 7. Generated Indexes and Links

Directory `index.md` files are generated deterministically from concept
frontmatter and immediate child directories. They contain only:

- Title and relative link.
- One-sentence description.
- Type and lifecycle marker when useful.

Detailed status, dates, and conclusions stay in concept frontmatter or body.
Agents do not manually maintain long status summaries in indexes.

Generated routers carry `generated: true` and are derived navigation artifacts,
not authoritative claims. They are exempt from human approval only when their
bytes exactly match the versioned generator output for the recorded input
manifest. Strict validation rejects manual edits or stale generated output, and
regeneration replaces it transactionally. Non-generated routers follow normal
approval rules.

The router input manifest contains normalized metadata hashes for immediate
non-generated concepts and child directories. Generated routers and `.eos/`
state are excluded from that input set, preventing self-referential hashes.

Normal Markdown links form the concept graph. The indexer records forward and
reverse links and reports:

- Broken links.
- Orphan concepts.
- Duplicate canonical resources.
- Deprecated concepts still linked as current truth.
- Cyclic supersession relationships.

## 8. Local Retrieval Engine

The implementation is a Python 3.12 CLI using:

- `argparse` for commands.
- `sqlite3` with FTS5 for lexical search.
- `PyYAML.safe_load` for frontmatter.
- Standard-library path, hashing, JSON, and subprocess APIs.

EOS provisions an isolated runtime under
`~/.local/share/eos/kb/.venv`. The generated SQLite database and session state
live under `~/.local/state/eos/kb/` and are never committed.

Primary commands:

```text
kb init
kb index [--rebuild]
kb validate [--strict]
kb search <query> [filters]
kb show <concept> [--section <heading>]
kb related <concept>
kb context <query> --budget <tokens>
kb status
kb stale
kb audit
kb checkpoint
kb propose
kb review [<proposal>|direct-change]
kb promote
kb deprecate
kb session start|resume|checkpoint|end|recover
kb bug start|record|status|block|resume|complete
```

Workspace detection uses an EOS registry:

```yaml
workspaces:
  $HOME/work/backend-project:
    kb: $HOME/work/knowledge
    project: backend-project
  $HOME/personal/research-project:
    kb: $HOME/personal/knowledge
    project: nlp-to-llm-evolution
```

The registry supports `~` and environment-independent home expansion so EOS is
reproducible on another machine.

## 9. Search and Context Assembly

Retrieval runs in this order:

1. Detect KB and project from the current working directory.
2. Parse exact identifiers from the query, including errors, tickets, symbols,
   flags, fields, paths, and hashes.
3. Filter by project, type, lifecycle, component, and freshness.
4. Rank exact metadata and identifier matches.
5. Rank title, tags, components, symptoms, description, headings, and body using
   FTS5/BM25.
6. Expand one graph hop from strong candidates.
7. Penalize stale, draft, machine-only, and deprecated concepts.
8. Return compact metadata cards before loading bodies.

`kb context` assembles a bounded package containing:

- Relevant concept summaries.
- Only selected sections from large files.
- Verification and freshness state.
- Source paths and revisions.
- Contradictory or superseding concepts.
- Unresolved questions.

The token budget is a hard bound in EOS estimated-token units. The default
offline estimator is `ceil(UTF-8 byte length / 2)`, deliberately conservative
for English, Markdown, and source code. Agent-specific tokenizers may be added,
but tests and CLI output always declare the estimator used. `kb context` stops
before the next complete result would exceed the requested budget. Freshness and
contradiction warnings are reserved first and must never be silently omitted to
fit more prose.

Vector retrieval is deferred. It may be added as a fallback for vague queries
after lexical retrieval is measured and only if benchmark recall requires it.

## 10. Freshness Lifecycle

The freshness engine detects four classes:

1. **Source drift**: a tracked source changed after concept verification.
2. **Time drift**: `stale_after` has passed.
3. **Contradiction**: active concepts declare the same `eos.claims[].id` with
   different normalized values.
4. **Coverage drift**: a changed path intersects a declared project coverage
   rule or concept `eos.source_paths`, but its exact resource-and-blob mapping is
   neither current nor pending under the rules in Section 6.

Source drift uses Git blob hashes and revisions when the source is in Git, and
content hashes or modification metadata for approved external sources. Derived
freshness state is stored outside Markdown so audits do not create content
churn.

The baseline is the concept's recorded `eos.source_revision` plus per-path blob
hashes in the generated manifest. A change is meaningful when Git reports a
content change under a declared, non-ignored coverage path. Rename detection is
enabled. Untracked paths and sources without a baseline produce `unknown`, not
`fresh`. Deterministic contradiction and coverage guarantees apply only to
concepts and paths carrying these explicit contracts.

Checkpoints run at:

- Agent startup.
- Explicit task checkpoints.
- Before commit or final completion where an agent supports hooks.
- Normal agent exit.
- The next startup after abnormal termination.
- Manual or scheduled `kb audit`.

SessionEnd remains useful but is never the only protection. A killed process is
recovered by comparing the repository and KB against the last recorded session
baseline on the next audit.

Search surfaces freshness labels and never presents stale knowledge as current
without a warning. Stable documents are not silently rewritten when drift is
detected.

## 11. Governance and Proposal Lifecycle

Agents may automatically:

- Record investigation evidence and session logs.
- Create structured knowledge proposals.
- Update generated indexes and search caches.
- Mark derived freshness state.

Agents may not automatically:

- Promote a proposal into stable knowledge.
- Change or remove an invariant.
- Deprecate current knowledge.
- Replace a human-verified claim.

Proposal states:

```text
captured -> ready-for-review -> accepted -> promoted
                              `-> rejected
                              `-> superseded
```

Allowed transitions are exactly:

- `captured -> ready-for-review`
- `ready-for-review -> accepted|rejected|superseded`
- `accepted -> promoted|superseded`

No transition out of `promoted`, `rejected`, or `superseded` is allowed. A new
proposal is required for later changes.

Each proposal contains:

- Target concept or proposed new path.
- Claim-level change summary.
- Supporting evidence and source paths.
- Confidence and known gaps.
- Suggested freshness metadata.
- Conflicts with existing concepts.

`kb review` presents proposals one at a time. `kb promote` applies only accepted
items, updates frontmatter, regenerates indexes, and records the promotion in
`log.md`.

Governance metadata is versioned inside each KB under `.eos/`:

- `.eos/approvals.jsonl`: append-only review records.
- `.eos/manifest.json`: generated current concept hashes and approved hashes.
- `.eos/schema-version`: active EOS KB schema version.

An acceptance record contains proposal ID, actor, timestamp, proposal content
hash, base target hash, proposed result hash, decision, and session evidence
reference. The base target hash is null for a new concept. Promotion requires
an accepted record whose proposal hash still matches and a live target whose
hash still equals the recorded base. The promoted concept must hash to the
accepted result hash before the manifest marks it approved. Deprecation uses the
same proposal and approval path.

This is an auditable single-user governance control, not an adversarial security
boundary. The configured human actor represents who approved a decision; it is
not cryptographic authentication. Direct edits to stable documents are allowed,
but `kb validate` marks their changed hash as unreviewed until an interactive
`kb review direct-change` records acceptance. Agents may present and record an
approval explicitly given in conversation, including the session reference, but
may never infer approval from silence or from passing tests.

Writes to a proposal, approval log, target concept, generated index, and
manifest are staged in a transaction directory. They replace live files only
after all validation succeeds. A partial failure leaves the previous state and
an actionable recovery record.

## 12. Executable Global Agent Policy

EOS becomes the canonical policy source:

```text
configs/agents/
|-- critical-rules.md
|-- global-context.md
|-- adapters/
|   |-- CLAUDE.md
|   |-- AGENTS.md
|   `-- GEMINI.md
`-- skills/
    |-- knowledge-management/SKILL.md
    `-- bug-investigation/SKILL.md
```

`critical-rules.md` contains only always-applicable rules:

- English or Hinglish, never Hindi.
- Plain dash, never the em dash character.
- Never add agent attribution to commits or PRs.
- Prefer correctness, robustness, scalability, and maintainability over
  development cost.
- Use the shared KB as the only durable agent memory.
- Investigate and reproduce bugs before implementing fixes.
- Stable KB changes require approval.

`global-context.md` contains KB roots, user-profile routing, and repository
instruction routing. Detailed multi-step behavior lives in skills.

Adapters are rendered deterministically from canonical fragments. Tests compare
their hashes or normalized contents to prevent drift.

## 13. Agent Integration

EOS installs the same canonical skills and policy into:

- Claude default, work, and personal profiles.
- Codex default, work, and personal profiles.
- Gemini CLI.
- Antigravity CLI and IDE profile directories.

All profiles use the same `kb` executable.

Launch lifecycle:

```text
profile wrapper
  -> eos agent doctor
  -> kb session start --cwd <workspace>
  -> mount relevant KB writable
  -> launch agent with critical policy
  -> kb session end --exit-code <status> on normal exit
```

Session state uses a generated UUID unless the agent supplies its native session
ID. It records agent/profile, workspace, project, start revision, changed paths,
active investigation IDs, parent session, owner process, lease timestamp, and
lifecycle state. Lifecycle states are `active`, `ended`, and `abandoned`;
checkpoint is an event, not a state.

- `kb session start` creates `active`; it never replaces an existing record.
- `kb session checkpoint` records an atomic snapshot and leaves the session
  active. Top-level `kb checkpoint` runs the KB audit and then checkpoints the
  active session as a portable convenience command.
- `kb session end` performs a final checkpoint and transitions `active -> ended`.
- Resume reuses the same session record when the native session ID matches and
  transitions `ended -> active`. An abandoned session requires explicit resume
  with the same native ID; otherwise a new child or successor session is used.
- Compaction checkpoints and restores the same session; it never creates a new
  governance identity.
- Subagents receive a child session with `parent_session_id` and may capture
  evidence and proposals but may not promote knowledge.
- Concurrent sessions use separate append-only event files and SQLite WAL mode.
  Proposal IDs are UUIDs, writes use file locks plus atomic rename, and one
  session cannot overwrite another session's baseline.
- `kb session recover` marks an active session abandoned only when its owner
  PID and process-start token no longer identify a live process. On platforms
  where process identity cannot be inspected, the configured lease expiry is
  used and defaults to five minutes. Recovery merges changed-path evidence into
  the next audit and never auto-promotes proposals. No other lifecycle
  transitions are valid.

Claude-specific hardening:

- Pass `critical-rules.md` through `--append-system-prompt-file`.
- Set `attribution.commit` and `attribution.pr` to empty strings and
  `attribution.sessionUrl` to false.
- Set response language to English; the critical policy permits Hinglish.
- Install an `InstructionsLoaded` hook for observability.
- Use the exact `.claude/CLAUDE.md` casing.
- Use real `@AGENTS.md` imports where repository AGENTS rules apply.
- Add deterministic Stop and PreToolUse hooks where a rule can be checked
  mechanically.

Codex, Gemini, and Antigravity use their strongest available global instruction
surface plus launch wrappers and the shared skills. Agent-specific adapters may
differ, but policy content and CLI behavior do not.

## 14. Enforcement Model

Rules are classified by enforcement strength:

| Class | Examples | Enforcement |
|---|---|---|
| Deterministic | attribution, KB writable, metadata schema, link validity | settings, hooks, validators |
| Workflow-gated | bug reproduction, KB checkpoint, verification matrix | skill plus session ledger and Stop gate |
| Behavioral | concise style, intellectual honesty, decision quality | critical system policy plus adherence tests |

Deterministic rules must not rely on LLM compliance. Behavioral rules cannot be
guaranteed perfectly, so EOS measures them and keeps their instructions short,
specific, and high-salience.

The final-response checker detects the em dash character and Hindi Unicode
blocks. It asks the agent to correct the response before completion rather than
silently rewriting content.

## 15. Mandatory Bug-Investigation Workflow

The `bug-investigation` skill triggers for bugs, regressions, failing tests,
unexpected output, and production discrepancies.

State is stored under `~/.local/state/eos/kb/investigations/<session>.json`, not
inside a repository scratchpad.

Required phases:

1. **Classify and retrieve**
   - Record the reported symptom and user impact.
   - Search relevant KB failure modes, incidents, invariants, and runbooks.
   - Check freshness and contradictions before trusting retrieved knowledge.
2. **Reproduce**
   - Reproduce through the closest available end-user path.
   - Record environment, inputs, exact commands, expected behavior, actual
     behavior, and artifacts.
   - If reproduction is blocked, record the blocking condition and closest
     faithful substitute. Do not present an unverified guess as root cause.
3. **Map the system**
   - Trace entrypoint to outcome.
   - Enumerate readers, writers, downstream consumers, flags, environments, and
     adjacent cases.
   - Search the repository and tests for blast radius.
4. **Hypothesize and disconfirm**
   - Record plausible hypotheses.
   - For each, record supporting evidence, contradicting evidence, and an
     explicit test.
   - Do not select a root cause until alternatives consistent with the symptom
     are tested or explicitly left unresolved.
5. **Fix gate**
   - State the causal chain from input to observed failure.
   - Create a failing automated test or executable reproduction.
   - Only then permit implementation.
6. **Verify**
   - Re-run the original E2E reproduction.
   - Run negative cases, adjacent cases, regressions, lint, and relevant tests.
   - Record remaining uncertainty.
7. **Capture**
   - Create a failure-mode or incident proposal when the learning is durable.
   - Run `kb checkpoint` before completion.

The workflow does not require an arbitrary number of hypotheses when evidence
supports only one. It does require the agent to state why alternatives are not
plausible and what cases were checked.

Investigation lifecycle is:

```text
new -> reproducing -> investigating -> root-caused -> fixing -> verifying -> complete
          |              |                |            |          |
          `--------------`----------------`------------`----------`-> blocked
blocked -> <recorded prior state>
```

The normal forward transitions are exactly those on the first line. Any active
phase may transition to `blocked` with blocker evidence and a recorded prior
state. `kb bug resume` returns only to that prior state after recording what
removed the blocker. `blocked` is a valid task outcome but is not `complete`.

`kb bug complete` is allowed only from `verifying` and rejects a ledger without
reproduction evidence, causal chain, affected-case inventory, and verification
results. Fixing state requires `root-caused` plus a failing test or executable
reproduction reference. When faithful reproduction is unavailable, the task
must remain blocked; the agent may document the closest substitute and request
what is needed, but may not implement an asserted fix or mark the investigation
complete.

Task classification is defense in depth:

- Skill descriptions trigger on bug, regression, failed test, unexpected output,
  and production discrepancy language.
- Claude's UserPromptSubmit hook adds a reminder for deterministic lexical
  matches.
- Claude's Stop hook evaluates the transcript when no investigation ledger was
  opened and blocks completion if the task was a bug fix without the required
  evidence.
- Other agents use their strongest native equivalent plus exit audit. Behavioral
  adherence is measured because no cross-agent hook can perfectly classify all
  natural-language tasks.

## 16. Hooks and Abnormal-Termination Handling

Claude uses native hooks where available:

- `InstructionsLoaded`: record loaded instruction paths and reasons.
- `SessionStart`: inject project, freshness, and pending-proposal summary.
- `UserPromptSubmit`: remind or activate bug/KB workflow when classified.
- `PreToolUse`: enforce deterministic commit-attribution policy.
- `PostToolUse`: update changed-source session state.
- `PreCompact` and `PostCompact`: persist and restore active investigation and
  KB checkpoint state.
- `Stop`: block success completion for an incomplete required checkpoint; allow
  a recorded investigation blocker to be reported as blocked work.
- `SessionEnd`: capture remaining proposals.

Other agents use their native hook equivalents when reliable. The wrapper and
next-start audit remain the portable fallback.

Hooks must be fast, deterministic where possible, fail with actionable errors,
and avoid hidden network calls. Model-based hook checks are limited to behavior
that cannot be classified mechanically.

## 17. Validation and Error Handling

`kb validate` reports errors with file, field, and remediation:

- Invalid or missing `type`.
- Unsafe or invalid YAML.
- Broken links and invalid supersession chains.
- Duplicate canonical resources.
- Index drift.
- Orphans and unreachable stable concepts.
- Missing tracked sources.
- Unapproved stable changes.
- Search-cache schema mismatch.

The prose schema is backed by versioned machine-readable schema files and golden
CLI fixtures checked into EOS. Every supported command has success, validation
failure, recovery, and output-shape fixtures so planning does not depend on prose
interpretation.

Normal search remains available when some documents are invalid, but invalid
documents are labeled and excluded from authoritative results. Strict mode is
used by EOS verification and migration completion.

The index is rebuilt transactionally into a temporary database and atomically
replaced only after successful validation. A failed rebuild leaves the last good
index available.

## 18. Migration Strategy

Migration is incremental and lossless:

1. Inventory and back up both KBs. Write a migration manifest containing every
   source path, original hash, proposed target path, inferred type, and planned
   metadata before changing content.
2. Install the tolerant parser, registry, and indexer.
3. Add deterministic frontmatter to existing concepts using path and title
   inference only. Do not synthesize unverified descriptions or claims.
4. Generate canonical `index.md` routers while retaining compatibility files.
5. Fully migrate the smaller personal KB.
6. Migrate high-value work KB routes and current work project concepts.
7. Migrate remaining work concepts and run strict validation.
8. Use section-level indexing for large legacy documents immediately; split
   documents only when a clear concept boundary exists.
9. Keep logs, proposals, and archives searchable only through explicit filters.
10. Switch agent instructions and wrappers after retrieval and adherence tests
    pass.

Migration defaults to dry-run and emits a human-reviewable report. Applying a
migration requires the unchanged manifest hash. Backups preserve original paths
and permissions, and rollback restores from the manifest rather than deleting
unknown files.

No existing knowledge is deleted during migration. Deprecated or duplicated
material is preserved with explicit lifecycle metadata until reviewed.

## 19. Reproducibility

EOS bootstrap installs:

- KB runtime and CLI.
- Registry templates.
- Canonical agent policy and adapters.
- Shared skills.
- Agent hooks and profile wrappers.
- Work and personal KB scaffolds when absent.
- Tests and an `eos agent doctor` command.

Private KB content remains outside the EOS Git repository. EOS contains only
schemas, templates, tooling, and installer logic.

Running bootstrap repeatedly is idempotent. Existing files are backed up before
replacement, and generated files are rewritten only when content differs.

## 20. Verification and Evaluation

### Unit and integration tests

- Frontmatter parsing and schema validation.
- Deterministic index generation.
- FTS ranking for exact and conceptual queries.
- Section extraction and hard context budgets.
- Link graph and reverse-link generation.
- Source and time drift detection.
- Proposal lifecycle and approval gate.
- Workspace registry matching.
- Wrapper dry runs and profile path installation.
- Hook event input/output contracts.
- Abnormal termination followed by next-start recovery.

### Retrieval benchmark

Create 15 to 25 real work project debugging queries with expected concepts and measure:

- Recall at 5.
- Precision at 5.
- Tokens returned.
- Freshness and contradiction warnings.
- Time to first correct hypothesis.

Acceptance thresholds for the first benchmark are:

- 100 percent Recall@5 for exact identifiers, paths, flags, and error strings.
- At least 90 percent Recall@5 across all benchmark queries.
- 100 percent surfacing of known stale and contradiction warnings.
- Median `kb context` output at or below 1,500 EOS estimated-token units.
- No benchmark context above its requested 2,500-unit hard budget.

### Agent adherence matrix

Run isolated, non-repository test sessions for each supported agent/profile:

- Fresh session.
- Resume.
- Compaction.
- Subagent.
- Work and personal routing.
- Bug task requiring reproduction.
- KB-impacting task requiring a proposal.
- Commit attribution prohibition.
- Language and punctuation rules.

Tests prove both instruction loading and observable behavior. They do not expose
private repository context to external model providers.

Deterministic adherence checks must pass 100 percent. Behavioral checks run at
least three trials per supported profile and must pass at least 90 percent
overall, with no profile below 80 percent. A deterministic failure blocks EOS
verification. A behavioral regression blocks rollout of new instruction or hook
changes until reviewed.

### Completion criteria

- Both KBs pass strict structural validation.
- Work and personal routing is correct from registered workspaces.
- Retrieval benchmark meets the thresholds defined above.
- Critical deterministic rules pass for every installed profile.
- A killed agent session produces a recoverable checkpoint or drift warning on
  next start.
- A bug task cannot complete successfully through supported Claude hooks without
  reproduction and verification evidence. It may end as blocked only with an
  explicit reproduction or investigation blocker.
- Stable knowledge cannot change through `kb promote` without accepted review
  state.

## 21. Security and Privacy

- The KB engine is local and performs no network calls.
- Search caches contain KB text and therefore inherit KB filesystem permissions.
- Work and personal indexes are stored separately.
- Agent adherence tests run in isolated temporary directories.
- Work repository or KB content is never sent to a model solely to test whether
  global instructions loaded.
- Hook logs must not capture credentials, full environment dumps, or secret
  values.
- External sources remain untrusted evidence until verified.

## 22. Deferred Work

- Vector embeddings and semantic fallback.
- Long-running MCP knowledge server.
- Web UI or graph visualizer.
- Multi-user remote synchronization.
- Automatic promotion of stable knowledge.
- Automated credibility scoring beyond OKF trust signals.

These can be added behind the stable CLI and bundle contracts if measured needs
justify them.
