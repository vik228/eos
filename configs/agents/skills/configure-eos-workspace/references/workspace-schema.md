# EOS workspace schema

Profile workspaces live at:

```text
~/.config/eos/profiles/<profile>/workspaces/<name>.yaml
```

Complete definition:

```yaml
schema_version: 1
session: project
directory: $HOME/work/project
fallback_directory: $HOME/work
mode: tmux
windows:
  - name: editor
    command: nvim
  - name: shell
    command: zsh
```

Override a built-in layout:

```yaml
extends: backend
session: my-project
directory: $HOME/work/my-project
windows:
  - { name: editor, command: nvim }
  - { name: database, command: pgcli }
  - { name: shell, command: zsh }
```

Fields:

- `schema_version`: must be `1` after inheritance.
- `extends`: optional built-in workspace name. The overlay replaces arrays.
- `session`: tmux-safe name using letters, digits, dot, underscore, or hyphen.
- `directory`: required path; environment variables are expanded.
- `fallback_directory`: optional fallback when `directory` does not exist.
- `mode`: `tmux` or `wezterm-editor`.
- `editor_window`: window moved to WezTerm in `wezterm-editor` mode; defaults to
  `editor`.
- `windows`: non-empty ordered list of unique names and shell commands.

Commands:

```bash
EOS_PROFILE=<profile> eos workspace validate <name>
EOS_PROFILE=<profile> eos workspace preview <name>
EOS_PROFILE=<profile> eos workspace launch <name>
```
