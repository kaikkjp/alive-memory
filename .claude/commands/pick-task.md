Read TASKS.md. Find the first task with status `READY`.

Print:
- Task ID and title
- Priority
- Dependencies (and whether they're met)
- Full description
- Scope (files you may touch)
- Scope (files you may NOT touch)
- Tests required
- Definition of done

If no task is READY, say "No tasks queued. Ask the operator to flip a task to READY in TASKS.md."

If multiple tasks are READY, warn: "Multiple tasks are READY — only one should be READY at a time unless scopes don't overlap." Then list them.
