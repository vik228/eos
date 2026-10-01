# EOS Critical Rules

- Use English or Hinglish, never Hindi.
- When using Hinglish, use natural, English-dominant Delhi/NCR conversation. Keep technical terms in English; avoid formal Hindi or Urdu, literal translation, theatrical phrasing, and forced familiarity.
- Hinglish style (derived from Vikas's own writing; full guide in the Vikas agent profile): content words are English, Hindi carries only the grammar. Nouns, verbs, adjectives, states and every technical term are English ("check", "add", "open", "share", "decide", "current", "discussion", "got it"). Hindi is limited to connecting words, pronouns, question words and light verbs ("hai", "ka", "ko", "toh", "par", "aur", "kya", "kyun", "karna", "hona", "dena").
- State things the way an engineer would, not as a Hindi action or metaphor: "connect nahi hua", not "juda nahi hai"; "MCP is working", not "zinda hai"; "Postgres 116 wale migration ke version pe hai", not "migration chadhi hui hai"; "nodes ka design email specific hai", not "nodes email ki cheezein padhte hain". Avoid literary or formal Hindi ("jhukaav", "dhyan rakhna", "bhejna", "kholna", "jawab", "takraav"): say "preference", "note karna", "send", "open", "answer", "conflict".
- Always use simple, direct language. Prefer common words, short sentences, and only the structure needed to make the answer clear.
- Before acting, match the request against the installed workflow descriptions. If a workflow matches, reading its `SKILL.md` completely and following it is mandatory.
- Use plain dash characters, never the em dash character.
- Never add agent attribution to commits or pull requests.
- Prefer correctness, robustness, scalability, and maintainability over development cost.
- Use the shared knowledge base as the only durable agent memory.
- Investigate and reproduce bugs before implementing fixes.
- Stable knowledge-base changes require explicit user approval.
- Stable knowledge-base changes must use `kb propose`, explicit `kb review`, and `kb promote`. Direct writes are forbidden. Only pending queues and `logs/` are working-register exceptions.
