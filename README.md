# oh-my-council (omc)

Multi-agent orchestrator that cuts Claude token spend by delegating the
"typing" part of software work to cheap models while keeping Claude as
project manager and Codex as technical lead.

- **Claude** = PM: takes requirements, splits tasks, accepts/rejects milestones
- **Codex CLI** = tech lead: writes per-file specs, reviews worker output,
  runs security-style code review
- **Cheap workers** (GLM5 primary → MiniMax-M2.5 fallback via
  LiteLLM / OpenAI-compatible): write the actual code and run audits

All orchestration state, prompts, and replies are persisted to
`docs/projects/<id>/` (SQLite + markdown) so runs can be resumed, replayed,
and audited.

## Install

Requires **Python ≥ 3.11** and the **Codex CLI ≥ 0.118** on `$PATH`.

```bash
# From a checkout (recommended while unreleased)
uv sync --all-extras
uv run omc --help

# Or install the built wheel
uv build                  # produces dist/oh_my_council-*.whl
pipx install dist/oh_my_council-*.whl
omc --help
```

### Credentials

Create `~/.config/oh-my-council/.env` (permissions `0600`). Never commit
this file. Minimum keys:

```dotenv
# Primary worker/auditor provider
OMC_WORKER_VENDOR=zai
OMC_WORKER_MODEL=zai/glm-5.1
OMC_WORKER_API_BASE=https://llm.sca.im/v1/chat/completions
OMC_WORKER_API_KEY=sk-...

# Optional fallback — used when primary throws (429/5xx/parse fail)
OMC_WORKER_FALLBACK_VENDOR=minimax
OMC_WORKER_FALLBACK_MODEL=MiniMax-M2.5
OMC_WORKER_FALLBACK_API_BASE=https://api.minimaxi.com/v1/chat/completions
OMC_WORKER_FALLBACK_API_KEY=sk-...

# Codex tuning (optional)
OMC_CODEX_REASONING_EFFORT=low     # default; "high" hangs on long specs
OMC_CODEX_TIMEOUT_S=300            # default
```

The api_base may or may not include `/chat/completions` — `config.py`
normalizes either form.

## Typical CLI Flow

```bash
# 1. Create a project scaffold under docs/projects/<date>-<slug>/
omc init my-feature

# 2. Write the requirement
$EDITOR docs/projects/<id>/requirement.md

# 3a. Let Codex decompose the requirement into tasks automatically
omc plan <project-id>
#   …or manually seed one task (whitelist the files the worker may touch)
omc task add <project-id> T001 \
    --path-whitelist "src/pkg/foo.py,tests/test_foo.py"

# 4. Run the full pipeline for a task
#      produce_spec (Codex) → write (worker) → review (Codex) → audit (worker)
omc run <project-id> T001

# 5. Inspect
omc tail <project-id> --n 20
omc budget <project-id>
```

### Fake pipeline (no network)

```bash
omc run-fake <project-id> T001   # stubs all LLM calls, useful for smoke tests
```

## Using omc from Claude Code

omc ships an MCP stdio server so Claude Code can drive the orchestrator
as a tool. Register it once:

```bash
claude mcp add oh-my-council -- omc mcp
```

(Or add it to `.mcp.json` at the root of whichever repo you want Claude
Code to orchestrate.)

Inside a Claude Code session you can then ask natural-language things
like:

- *"Use oh-my-council to start a new project called `auth-refactor`,
  write the requirement, seed three tasks, and run T001."*
- *"Show me the last 20 interactions for project `2026-04-13-auth-refactor`."*
- *"What's the current USD spend on project X?"*

The MCP tools map 1:1 to the CLI subcommands — the Claude side does the
task decomposition, omc does the per-task dispatch to cheap workers.

## Repository Layout

```
src/omc/
  cli.py              # subcommands (init, task add, run, tail, budget, mcp)
  dispatcher.py       # per-task state machine: spec → write → review → audit
  clients/
    real_codex.py     # Codex CLI wrapper (spec / review / escalation)
    real_worker.py    # LiteLLM worker with provider-chain fallback
    real_auditor.py   # LiteLLM auditor with provider-chain fallback
    codex_cli.py      # subprocess bridge to `codex exec`
  gates/              # path_whitelist, syntax, hallucination
  budget.py           # L1 retries / L2 escalation / L3 task tokens / L4 project $
  store/              # sqlite + markdown layout
```

## Development

```bash
uv sync --all-extras
uv run pytest          # 120+ tests
uv run ruff check src tests
```

Runtime artifacts (sqlite, workspace, tasks/milestones md) are
gitignored. Anything inside `docs/projects/*/` that could contain LLM
prompt/response bodies is excluded by default.

## Releasing

Tag a commit with `vX.Y.Z` and push. The `release.yml` workflow will:

1. Build wheel + sdist with `uv build`.
2. Publish to PyPI via trusted publishing (configure the `pypi`
   environment in repo settings → Environments, then register the
   repo as a trusted publisher on PyPI).
3. Create a GitHub Release with auto-generated notes and the dist
   artifacts attached.

```bash
git tag v0.1.0 && git push origin v0.1.0
```

## License

MIT — see [LICENSE](LICENSE).
