---
type: decision
title: Check Acceptance Results
---

Evaluate whether acceptance tests passed. If passed, route to merge request; otherwise route to failure reporting.

## Next
- [[request-merge]] — when: tests_passed == true
- [[report-failure]] — when: tests_passed == false

## Output
```json
{
  "type": "object",
  "properties": {
    "route": {
      "type": "string",
      "enum": ["request-merge", "report-failure"]
    }
  },
  "required": ["route"]
}
```
