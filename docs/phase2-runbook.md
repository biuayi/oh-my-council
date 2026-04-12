# Phase 2 Runbook — Real Backends

Phase 2 把 MVP 从 Fake 客户端切到真实 LLM（LiteLLM 走 MiniMax/GLM5/Gemini 等 OpenAI 兼容接口）+ 真实 Codex CLI。本文描述装配、触发、排错。

## 先决条件

- Python 3.11+，uv 已装
- `codex` CLI 可执行（`codex --version`）
- 凭据文件：`~/.config/oh-my-council/.env`（权限 0600），最小字段：
  ```
  OMC_WORKER_VENDOR=minimax
  OMC_WORKER_MODEL=MiniMax-M2.5
  OMC_WORKER_API_BASE=https://api.minimaxi.com/v1/chat/completions
  OMC_WORKER_API_KEY=sk-...
  ```
  可选：`OMC_CODEX_BIN`（默认 `codex`）、`OMC_CODEX_TIMEOUT_S`（默认 `120`）

## 装依赖

```bash
uv sync --extra dev
```

## 日常命令

```bash
# 初始化项目（在当前目录 docs/ 下生成 scaffold）
uv run omc init my-demo
# 编辑需求
$EDITOR docs/projects/<date>-my-demo/requirement.md
# 用真实 backend 跑一个任务
uv run omc run <date>-my-demo T001
# 旧的 fake pipeline（烟测，不花钱）
uv run omc run-fake <date>-my-demo T001
```

## 测试

```bash
# 常规测试（排除 slow）
uv run pytest

# 真实 E2E（需要 .env + codex + 网络）
uv run pytest -m slow -v
```

`slow` 标记的测试默认被 `addopts = -m 'not slow'` 排除，不会在 CI 上误跑。

## 架构要点

- `omc.config.load_settings()` 读 `~/.config/oh-my-council/.env`（或 `OMC_ENV_FILE`）
- `LiteLLMWorker` / `LiteLLMAuditor` 走 `openai/<model>` 前缀 + `api_base` 覆写，同一条路径覆盖 MiniMax / GLM / Gemini
- `RealCodexClient` 用 `subprocess` 跑 `codex exec`
  - `produce_spec` / `review`：`--sandbox read-only`
  - `dispatch_escalation`（L1 耗尽后 Codex 下场）：`--sandbox workspace-write`
- `hallucination gate` 用 `sys.stdlib_module_names` + `pyproject.toml` 声明 + `importlib.util.find_spec` + `hasattr` 校验 Codex 审查时列出的 symbols
- 预算 L1→L2→L3：worker 失败 3 次转 Codex；Codex 失败 1 次转 BLOCKED；token 超 200k 转 OVER_BUDGET
- `AsyncDispatcher` 用 `asyncio.Semaphore(n)` + `asyncio.to_thread` 并发跑同步 `Dispatcher.run_once`

## 故障排查

| 症状 | 排查 |
|---|---|
| `missing required env keys` | 检查 `.env` 是否四个 `OMC_WORKER_*` 全填 |
| `codex timeout after 120s` | 提高 `OMC_CODEX_TIMEOUT_S`，或检查 codex CLI 网络 |
| Worker JSON 解析失败 (`WorkerParseError`) | MiniMax 有时包 fence；解析器已容忍 ```json ... ```，但如果模型给出多段代码，需要调整 prompt |
| `LiteLLMAuditor` 返回 `passed=False unparseable` | 故意 fail-closed。看 `audit_md` 原文再调模型或 prompt |
| 路径白名单 violation | 任务 `path_whitelist` 与 Codex spec 的 `path_whitelist` 交集判定；确认两边一致 |
| `OVER_BUDGET` | L3 是 token 硬顶（默认 200k / task）。可调 `BudgetTracker(Limits(token_limit=...))` |
| `BLOCKED / escalation_exhausted` | L1+L2 全耗尽。查 `docs/projects/<id>/reviews/*.md` 看 Codex review 为什么拒绝 |

## 已知限制

- LiteLLM provider 暂时只走 OpenAI 兼容格式（`openai/<model>` + `api_base`）。原生 LiteLLM provider 前缀（例如 `minimax/...`）留到 Phase 3 评估。
- L4 USD 项目级预算未接入（Phase 3）。当前只有 L1/L2/L3。
- `compression_checkpoints` 表已建但还没写入逻辑（γ 路线）。
- Multi-project 并行调度、worker A/B 比分、tmux/TUI 全在 γ。

## 下一步（Phase 3 预告）

MCP server + slash commands + `claude -p` 里程碑验收 + tmux 面板 + 多项目并行 + USD 级预算追踪。
