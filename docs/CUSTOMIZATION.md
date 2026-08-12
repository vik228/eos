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

## Declarative workspace layouts

Workspace composition can be customized without editing EOS scripts. Create:

```text
~/.config/eos/profiles/<profile>/workspaces/<workspace>.yaml
```

For a small customization, inherit a built-in layout. A supplied `windows`
list replaces the inherited list, so order and membership remain explicit:

```yaml
extends: backend
session: my-backend
directory: $HOME/work/my-backend
windows:
  - { name: editor, command: nvim }
  - { name: database, command: pgcli }
  - { name: shell, command: zsh }
```

Alternatively, define a complete layout with `schema_version: 1`, `session`,
`directory`, `mode`, and `windows`. Supported modes are `tmux` and
`wezterm-editor`.

Validate and preview before launch:

```bash
EOS_PROFILE=work eos workspace validate backend
EOS_PROFILE=work eos workspace preview backend
EOS_PROFILE=work eos workspace launch backend
```

Window commands are executable local shell commands. Keep profile YAML private,
review generated commands, and do not place credentials directly in it.

## Agent-assisted setup

EOS installs the `configure-eos-workspace` skill for supported agents. A user
can ask Claude or Codex to configure a profile in plain language. The agent will
ask exploratory questions one at a time about:

- the type of work and repositories
- tools and persistent windows
- editor placement
- knowledge-base routing
- preferred explanation style, pacing, and pushback
- private context that belongs only to the profile

It then separates runtime config, workspace YAML, and agent `context.md`, shows
the proposed changes, validates the layout, and previews it before applying.

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
