# Issue Tracker: GitHub Issues

Issues for tequila-mule are tracked in [GitHub Issues](https://github.com/crashfrog/tequila-mule/issues).

## Creating Issues

Use `gh issue create` or the GitHub web UI. Include:
- Clear title (one sentence)
- Description with context, reproduction steps (if bug), or acceptance criteria (if feature)
- Relevant labels (applied by maintainer during triage)

## Issue Labels

See `triage-labels.md` for the canonical label vocabulary.

## Workflow

1. **Incoming issue** → `needs-triage`
2. **Needs more info** → `needs-info` (awaiting reporter)
3. **Ready for implementation** → `ready-for-agent` (fully specified, agent-ready) or `ready-for-human` (human judgment needed)
4. **Won't be actioned** → `wontfix`

Use `gh issue view <number>` to inspect issue state and labels.
