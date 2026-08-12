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

## Knowledge bases

Tracked KB files are generic scaffolds. Bootstrap does not overwrite an existing
work or personal KB unless an installer is explicitly run with `--force`.
Private projects and organization context belong only in the installed KB.

## Updating configuration

After editing `.eos.local` or `.eos-agent-context.local.md`, run:

```bash
scripts/render-local-config
scripts/install-agent-instructions
```

Run `bootstrap/verify.sh` after broader changes.
