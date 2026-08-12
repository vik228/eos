# Contributing to EOS

EOS is opinionated local infrastructure, but contributions that make it safer,
clearer, more configurable, or useful to more people are welcome.

## Ways to Contribute

- Report a reproducible bug through a GitHub issue.
- Propose a workflow or customization improvement through GitHub Discussions.
- Improve documentation, tests, portability, or installation safety.
- Submit a pull request for an agreed change.

For significant behavior or architecture changes, start with a Discussion or
issue before implementation. This avoids spending time on a direction that may
not fit EOS.

Do not use public issues, discussions, or pull requests for credentials,
private repository details, employer/customer information, or local machine
configuration.

## Development Flow

1. Fork the repository or create a branch in a permitted clone.
2. Branch from the latest `main`:

   ```bash
   git switch main
   git pull --ff-only
   git switch -c feat/short-description
   ```

3. Keep the change focused and add or update tests for behavior changes.
4. Run the relevant focused tests and, when practical, the full verification:

   ```bash
   bootstrap/verify.sh
   ```

5. Push the branch and open a pull request against `main`.

Direct pushes to `main` are not allowed. Every change must use a pull request
with resolved conversations. Reviews are encouraged and can become mandatory
when the project has more than one maintainer; a required external approval
would deadlock a solo-maintainer repository today.

## Pull Request Expectations

- Explain the user problem and resulting behavior.
- Include reproduction steps for bug fixes.
- List the tests that were run and any remaining platform uncertainty.
- Keep public examples generic and configurable.
- Preserve backward compatibility unless the breaking change is explicit and
  justified.
- Update user-facing documentation when commands or behavior change.
- Never add agent attribution or session URLs to commits or pull requests.

## Engineering Guidelines

- Prefer correctness, robustness, and maintainability over implementation
  convenience.
- Keep scripts explicit and safe to rerun.
- Back up user-owned files before replacing them.
- Keep machine-specific values in ignored local configuration.
- Reproduce bugs through the closest user-visible path before fixing them.
- Treat lint failures, test failures, UI defects, and flakiness as real defects.
- Do not commit secrets or private organizational context.

## Commit Style

Use a short imperative subject that describes the outcome, for example:

```text
Add profile-scoped workspace validation
Fix Markdown preview tab isolation
Document agent-assisted setup
```

## License

By contributing, you agree that your contribution will be licensed under the
repository's [MIT License](LICENSE).
