# Customizing EOS

EOS ships as an opinionated macOS setup. Machine identity and project topology
are local configuration, not tracked source.

## First-run configuration

```bash
cp eos.local.example .eos.local
$EDITOR .eos.local
bootstrap/bootstrap.sh
```

`.eos.local` is ignored by Git. It configures:

- user name and work/personal Git emails
- work, personal, research, and tools roots
- work and personal knowledge-base roots
- backend, research, and algorithm workspace directories
- the work KB project slug
- optional local agent context

Example:

```bash
: "${EOS_USER_NAME:=Your Name}"
: "${EOS_WORK_GIT_EMAIL:=you@company.example}"
: "${EOS_PERSONAL_GIT_EMAIL:=you@example.com}"
: "${EOS_BACKEND_DIR:=$HOME/work/backend}"
: "${EOS_RESEARCH_DIR:=$HOME/personal/research-project}"
: "${EOS_WORK_KNOWLEDGE_ROOT:=$HOME/work/knowledge}"
: "${EOS_PERSONAL_KNOWLEDGE_ROOT:=$HOME/personal/knowledge}"
```

The bootstrap renders machine-specific Git and agent files under
`~/.config/eos/generated` and links the active applications to those files.
Tracked source remains publishable and local reruns retain the same behavior.

## Local agent context

Create `.eos-agent-context.local.md` when agents need private repository routes,
employer rules, biography, or customer context. This file is ignored by Git and
is appended only to locally generated agent instructions.

Behavioral defaults such as direct feedback, first-principles reasoning,
English-dominant Hinglish, and the branching-discussion workflow remain tracked
because they are part of EOS's product opinion.

## Named profiles

Users can add any number of private overlays without editing EOS:

```bash
eos profile init work
eos profile init research
EOS_PROFILE=work eos profile show
```

Each profile lives under `~/.config/eos/profiles/<name>/`. Its `config` file can
override identity, paths, KB roots, project slugs, or other EOS variables. Its
`context.md` file is appended only to locally generated agent instructions.

Activate a profile per command or for the current shell:

```bash
EOS_PROFILE=work backend
export EOS_PROFILE=research
scripts/install-agent-instructions
```

Machine defaults load from `.eos.local`; the selected profile loads afterward
and may override them. Both layers remain outside Git.

### Example research profile

Edit `~/.config/eos/profiles/research/config`:

```bash
EOS_RESEARCH_DIR="$HOME/research/my-project"
EOS_RESEARCH_PROJECT_SLUG="my-research"
EOS_PERSONAL_GIT_EMAIL="research@example.com"
EOS_RESEARCH_TMUX=1
```

Edit `~/.config/eos/profiles/research/context.md`:

```markdown
# Research profile

- Use first-principles explanations.
- Keep experiments reproducible.
- Store durable findings in the research knowledge base.
```

Then launch it with:

```bash
EOS_PROFILE=research research
```

### Research editor layout

By default, when `research` is launched directly inside WezTerm, Neovim opens
in a separate WezTerm pane while support tools remain in tmux. To place Neovim
inside the research tmux session instead, set:

```bash
EOS_RESEARCH_TMUX=1
```

This may be set globally in `.eos.local`, in a named profile, or for one
command.

## Current workspace-layout boundary

User identity, paths, KB roots, project routing, agent context, and existing
workspace switches are configurable. The actual list of tmux windows and the
commands launched in each window are still declared in tracked scripts such as
`scripts/backend` and `scripts/research`.

Therefore, a user who wants a completely different workspace composition must
currently copy or edit a workspace script. For example, adding a database pane,
removing an agent, or changing window order is not yet expressible through a
user-owned profile alone.

A future declarative workspace layer could move window names and commands into
ignored profile configuration. Until then, profiles customize values and
behavioral switches, not the complete workspace graph.

## Knowledge bases

Tracked KB files are generic scaffolds. Bootstrap does not overwrite an existing
work or personal KB unless an installer is explicitly run with `--force`.
Private projects and organization context belong only in the installed KB.

## Updating configuration

After editing `.eos.local`, a profile config, or agent context, run:

```bash
scripts/render-local-config
scripts/install-agent-instructions
```

Run `bootstrap/verify.sh` after broader changes.
