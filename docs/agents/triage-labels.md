# Triage Labels

Canonical label vocabulary for tequila-mule GitHub Issues.

| Label | Meaning | Next Action |
|-------|---------|-------------|
| `needs-triage` | Maintainer needs to evaluate | Review, add context, decide if `needs-info` or `ready-*` |
| `needs-info` | Waiting on reporter | Pause until issue author responds |
| `ready-for-agent` | Fully specified, agent-ready | AFK agent can pick up and implement |
| `ready-for-human` | Needs human implementation | Assign to a team member |
| `wontfix` | Will not be actioned | Close issue |

## Applying Labels

Use `gh issue edit <number> --add-label <label>` or the web UI.

These labels are applied by:
- **Maintainer** during triage
- **`triage` skill** during automated triage runs
- **`to-issues` skill** when converting specs into issues
