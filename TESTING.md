# Testing

Run all checks:

```bash
~/personal/eos/bootstrap/verify.sh
~/personal/eos/tests/test_paths.sh
~/personal/eos/tests/test_symlinks.sh
~/personal/eos/tests/test_git_profiles.sh
~/personal/eos/tests/test_workspace_scripts.sh
~/personal/eos/tests/test_tools.sh
eos doctor
```

The verification suite includes a two-run temporary-HOME bootstrap test and 90
deterministic transport trials across all configured agent profiles.

Workspace scripts support non-interactive verification:

```bash
backend --dry-run
research --dry-run
paper --dry-run
algo --dry-run
leetcode --dry-run
write --dry-run
agents --dry-run
```
