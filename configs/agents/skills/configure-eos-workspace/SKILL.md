---
name: configure-eos-workspace
description: Configure an EOS installation through exploratory questions, including named profiles, agent response preferences, knowledge-base routing, tools, tmux windows, and declarative workspace YAML. Use when a user wants to set up EOS, customize how agents respond, create or change a profile, add or remove workspace windows, or build a complete workspace without editing scripts manually.
---

# Configure EOS Workspace

Guide the user from intent to a validated EOS profile. Keep the interaction
accessible to people who do not know shell, tmux, YAML, or agent configuration.

## Workflow

1. Read `references/workspace-schema.md` and the active `.eos.local` plus
   selected profile files when they exist.
2. Explore before editing. Ask one short question at a time. Cover only relevant
   branches:
   - what work the profile supports
   - repositories and knowledge locations
   - tools or views that should stay open
   - whether the editor belongs in tmux or a WezTerm pane
   - how agents should explain, challenge, pace, and structure responses
   - what context is private to this profile
3. Reflect the proposed profile in plain language. Separate:
   - runtime values in `config`
   - workspace composition in `workspaces/*.yaml`
   - agent behavior and private context in `context.md`
4. Never overwrite an existing profile file without showing the proposed diff
   and obtaining confirmation.
5. Write only under `~/.config/eos/profiles/<name>/` unless the user explicitly
   requests a tracked EOS default change.
6. Validate every YAML file with `eos workspace validate <name>`.
7. Show `eos workspace preview <name>` and explain the resulting layout in
   non-technical language.
8. Apply agent context with `EOS_PROFILE=<name>
   scripts/install-agent-instructions` after confirmation.
9. For a first-run setup, run `bootstrap/bootstrap.sh` only after approval. Do
   not let generic placeholder identity or paths become the intended final
   configuration.
10. Run `bootstrap/verify.sh` and report the exact launch command, normally
    `EOS_PROFILE=<name> <workspace>`.

## Guardrails

- Use `extends` for small changes to a built-in workspace.
- Treat window commands as executable local code. Do not insert downloads,
  credential handling, destructive commands, or elevated operations without a
  separate explicit request.
- Preserve user-authored comments and unrelated profile files.
- Do not put employer, customer, credential, or private repository context in
  tracked EOS files.
- Prefer recognizable tool names and explain any command the user did not name.
