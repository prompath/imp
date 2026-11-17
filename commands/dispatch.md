---
description: Make this session the dispatch gate - push queued notebook batches and pull results back, never run or approve anything
argument-hint: "[push | pull | inventory]"
disable-model-invocation: true
---

Invoke the Skill tool with `skill: "imp:dispatch"` and `args: "$ARGUMENTS"`, then follow the loaded skill. Load no other skill in this session.
