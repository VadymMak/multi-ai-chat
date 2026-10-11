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

### MANDATORY self-check (run BEFORE every debate_start / debate call)

State in ONE line: "This meets gate (a) because ___, (b) because ___, (c) because ___."
If you cannot complete all three, **do NOT debate — answer directly.**

### Gate (a/b/c) — ALL must hold

  (a) The problem involves **architecture, concurrency, security, data integrity,
      or an irreversible decision** — OR the agent already produced two conflicting
      answers this session.
  (b) A single-model answer is **low-confidence or high-ambiguity**.
  (c) The **cost of being wrong is high** (user-facing breakage, data loss,
      significant rework).

### NEVER debate these (answer directly instead)

| Task type | Examples |
|---|---|
| Review / preview / audit | "review our AI studio", "preview the new onboarding" |
| Summarize / explain | "summarize this PR", "explain how X works" |
| Prioritize / recommend | "what should we improve?", "give recommendations" |
| Look-at / tell-me | "look at X and tell me what's wrong" |
| List / overview | "list the features", "give me an overview" |
| Routine codegen | adding a field, renaming, simple refactor |
| How-to questions | "how do I use library X?" |

The server enforces this with a **cheap deterministic gate** — debate_start and
debate return `{skipped:true, reason, matched}` immediately for analysis tasks,
firing zero models and costing $0. Pass `force=true` to bypass for genuine edge cases.

### Which tool to use

| Scenario | Tool |
|---|---|
| rounds=1, verify=False, quick question | `debate()` — blocking, fast |
| rounds=1, verify=True OR rounds=2 | **`debate_start()` + poll `debate_result()`** |
| project-grounded (context injection) | **`debate_start(project_id=…)` + poll** |

`debate_start()` returns `{debate_id, status:"running"}` immediately.
Poll `debate_result(debate_id)` every ~5 s until `status != "running"`.
Always pass `project_id` or `folder_identifier` so the debate is grounded.
Give up after 3 minutes if still running.

```
# Self-check first: "This meets (a) X, (b) Y, (c) Z"
debate_id = debate_start(question=..., project_id=20, rounds=2, verify=True)
# poll loop:
while True:
    r = debate_result(debate_id)
    if r.status != "running":
        break
    sleep(5)
# If r.skipped == true: the gate fired — answer directly instead
```

`debate()` fires three paid models (~$0.10–0.40 per call) and takes 40–90s.
Use it sparingly as a deliberate escalation, not as a default answer path.
