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

## When to use debate()

Call `debate()` ONLY when ALL of the following hold:
  (a) The problem involves **architecture, concurrency, security, data integrity,
      or an irreversible decision** — OR the agent already produced two conflicting
      answers this session.
  (b) A single-model answer is **low-confidence or high-ambiguity**.
  (c) The **cost of being wrong is high** (user-facing breakage, data loss,
      significant rework).

**NEVER** call `debate()` for:
- Routine codegen or refactoring
- Simple explanations or "how to use X library" questions
- Questions with a well-known deterministic answer
- Tasks where a single confident model answer is sufficient

`debate()` fires three paid models (~$0.10–0.40 per call) and takes 40–90s.
Use it sparingly as a deliberate escalation, not as a default answer path.
