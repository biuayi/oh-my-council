# Phase 3b Milestone Verifier Runbook

## Prerequisites

- `claude` CLI v0.1.0+ installed and authenticated. Verify with:
  ```bash
  claude --version
  claude -p "hello"  # should succeed
  ```

## Two Paths to Verification

### Path 1: CLI (`omc verify`)

The orchestrator automatically spawns a subprocess Claude (`claude -p`) to render a milestone verdict:

```bash
omc verify 2026-04-12-myproject
```

**Returns exit codes:**
- `0` — ACCEPT (milestone approved)
- `3` — NEED_DETAIL (request clarification)
- `4` — REJECT (milestone not ready)
- `2` — project not found

**Console output:**
```
[ACCEPT] All tasks completed and tested.
  - Deploy to staging
  - Run smoke test
```

### Path 2: MCP Tool (`omc_verify`)

Within an active Claude Code session with oh-my-council MCP server running:

```
Call the `omc_verify` tool with project_id=`2026-04-12-myproject`.
Read the requirement + task list. Decide ACCEPT / NEED_DETAIL / REJECT.
```

The tool returns:
```json
{
  "project_id": "...",
  "requirement": "# Greet...",
  "tasks": [
    {"id": "T1", "status": "ACCEPTED", "attempts": 1},
    {"id": "T2", "status": "PENDING", "attempts": 0}
  ],
  "hint": "Decide based on requirement vs task statuses..."
}
```

## JSON Output Format

Claude must return (in CLI or MCP context):
```json
{
  "decision": "ACCEPT|NEED_DETAIL|REJECT",
  "summary": "Human-readable verdict (1-2 sentences)",
  "next_actions": ["action 1", "action 2"]
}
```

If the output is unparseable, fails-closed: **REJECT** automatically.

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| `claude: command not found` | Install Claude CLI: https://docs.anthropic.com/claude-code |
| `claude -p` hangs | Check auth: `claude login`; check network |
| Unparseable output error | Inspect Claude's actual stdout; ensure valid JSON in response |
| Task statuses stuck at PENDING | Run `omc run <project_id> <task_id>` to advance tasks |

## Known Limitations

- **No milestone DB**: A "milestone" = all tasks in the project at this moment.
- **No auto-escalation**: If CLI verify returns NEED_DETAIL, user manually escalates to Codex.
- **Single-step**: Cannot iterate (no retry loop if Claude's first answer is unclear).

## Example Workflow

```bash
# Initialize project
omc init my-feature

# Create and advance tasks (mock or real)
omc run 2026-04-12-my-feature T1

# Check milestone readiness
omc verify 2026-04-12-my-feature
# Output:
# [NEED_DETAIL] Unit tests incomplete.
#   - Add pytest markers for integration tests

# Fix issues, re-run
omc run 2026-04-12-my-feature T2

# Check again
omc verify 2026-04-12-my-feature
# Output:
# [ACCEPT] All deliverables complete.
```
