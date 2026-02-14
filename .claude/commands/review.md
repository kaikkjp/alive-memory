Run a post-implementation review of the most recent task.

Steps:
1. Run `git diff main --name-only` to see what changed
2. Read TASKS.md to find the task that was just completed (IN_PROGRESS or recently marked DONE)
3. Cross-reference changed files against the task's scope
4. Run `python -m pytest tests/ -v`
5. Run `python scripts/update_docs.py`
6. Summarize:
   - Files changed vs files in scope (any violations?)
   - Test results (all pass?)
   - Doc coverage (any new undocumented files?)
   - Ready to merge? Yes/No with reasons
