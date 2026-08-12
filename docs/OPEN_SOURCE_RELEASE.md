# Open-source Release Checklist

EOS is licensed under MIT and its tracked current tree is designed to contain
only generic defaults. Do not make an existing repository public without also
checking its history.

## Required checks

```bash
tests/test_open_source_config.sh
bootstrap/verify.sh
```

Install and run a dedicated secret scanner against the complete history before
publication. Pattern scans are useful but do not replace entropy and provider
signature detection.

```bash
gitleaks git --redact --no-banner .
```

## History boundary

Earlier private development commits may contain usernames, email addresses,
absolute paths, employer or customer context, and private project names. A
deletion in the latest commit does not remove that content from Git history.

For the first public release, prefer a clean public-history cut:

1. Keep the private repository and its history as the internal development
   archive.
2. Create a new public root commit from the reviewed current tree.
3. Verify ignored local files are absent.
4. Run current-tree and history secret scans on the public candidate.
5. Push the public history only after reviewing the exact remote and branch.

Do not force-push a rewritten history over an existing remote as part of normal
bootstrap or release automation.

## Files that must remain local

- `.eos.local`
- `.eos-agent-context.local.md`
- generated files under `~/.config/eos/generated`
- live work and personal knowledge bases
- MCP credentials and agent-provider authentication
- employer, customer, repository, staging, and production context
