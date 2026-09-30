---
type: task
title: Delegate Code Change to Harness
---

Call the `coding_agent` tool with `wait=true` to execute the requested coding task in an isolated worktree and verify acceptance tests.

## Next
- [[check-tests]]

## Output
```json
{
  "type": "object",
  "properties": {
    "task_id": {"type": "string"},
    "tests_passed": {"type": "boolean"},
    "summary": {"type": "string"}
  },
  "required": ["task_id", "tests_passed", "summary"]
}
```
