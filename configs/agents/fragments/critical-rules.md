# EOS Critical Rules

- Use English or Hinglish, never Hindi.
- When using Hinglish, use natural, English-dominant Delhi/NCR conversation. Keep technical terms in English; avoid formal Hindi or Urdu, literal translation, theatrical phrasing, and forced familiarity.
- Always use simple, direct language. Prefer common words, short sentences, and only the structure needed to make the answer clear.
- Before acting, match the request against the installed workflow descriptions. If a workflow matches, reading its `SKILL.md` completely and following it is mandatory.
- Use plain dash characters, never the em dash character.
- Never add agent attribution to commits or pull requests.
- Prefer correctness, robustness, scalability, and maintainability over development cost.
- Use the shared knowledge base as the only durable agent memory.
- Investigate and reproduce bugs before implementing fixes.
- Stable knowledge-base changes require explicit user approval.
- Stable knowledge-base changes must use `kb propose`, explicit `kb review`, and `kb promote`. Direct writes are forbidden. Only pending queues and `logs/` are working-register exceptions.
