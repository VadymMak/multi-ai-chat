# MANDATORY: Use Brain MCP for EVERY request

⚠️ RULE: You MUST call brain build_context_for_query BEFORE responding to ANY message.
No exceptions. Even for simple questions.

## At session start (run once per new session):
1. Call `brain get_skill "startup"` — returns the session-start checklist (active project, recent summaries, patterns).
2. Follow the steps it returns before doing other work.

## Required workflow for EVERY response:
1. FIRST: Call `build_context_for_query` with the user's question
2. THEN: Use returned context to answer

## Brain commands:
- `build context for query "question"` — ALWAYS call this first
- `search project files for "keyword"` — search codebase
- `get file content path/to/file` — read specific file
- `get file dependencies for path/to/file` — show imports
- `get_skill "<name>"` — load a skill from the library (e.g. `startup`, `commit-deploy`, `session-end`)
- `list_skills` — list all skills, or pass `category` to filter

## Error learning loop (WRITE path):
- Before non-trivial work: call `query_pitfalls(project_id=20)` — avoid known mistakes.
- When you hit a real error (failing command, stack trace, test failure): call `record_error`.
- After fixing it: call `record_fix(error_id=..., solution_pattern="one-line fix")`.

## IMPORTANT:
- Never skip Brain context step
- Never answer directly without calling Brain first
- Brain returns only relevant 4K tokens — fast and cheap
