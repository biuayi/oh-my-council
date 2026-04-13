# oh-my-council TODO (γ 延后功能)

MVP (β) 见 `docs/superpowers/specs/2026-04-12-oh-my-council-design.md`。
以下功能**不**进入 MVP, 在 β 跑通后再按需实现。

## 上下文管理

- [ ] **compression_checkpoints 真正生效**: agent (尤其是 Codex CLI 长会话) 接近 ctx 上限时自动浓缩; 浓缩前先写快照到 sqlite 的 `compression_checkpoints` 表, 保留 `carry_forward` JSON, 并把丢弃项的 MD 路径记入 `dropped_refs`, 便于回查。
- [ ] Claude 里程碑短调用也接入 checkpoint (避免单次短调用自身 ctx 溢出)。

## 调度与多项目

- [ ] 多项目并行调度 (当前 MVP 一次只跑一个 project)
- [ ] 单项目内 worker 并发数可配 (默认 2, γ 允许 1-8 动态调)
- [ ] 任务优先级 / 依赖图可视化

## 失败恢复与审计

- [x] 失败任务回放: `omc replay <project> <task>` 按时间序打印 interactions 链，`--max-chars` 可截断单条 body ✅
- [ ] diff 审阅 UI (TUI 或 Web): 里程碑验收时 Claude 要 `need_detail` 的场景, 人也能旁听
- [x] interactions 压缩归档: `omc archive-stale --days N [--output-dir DIR] [--remove]` — 批量 tar.gz 老项目到 `docs/_archive/` ✅

## 预算与观测

- [x] 预算预警 (非硬停): 到达 80% 时发提醒, 不中断 ✅ (`BudgetTracker.record_cost` 在跨越阈值时向 stderr 发一次 WARNING)
- [x] 每日/每周预算汇总报表 (跨项目): `omc report --period day|week|all` ✅
- [x] 模型调用成本分摊 (按 project / task): `omc report --by-task` ✅ (按 milestone 延后，尚无里程碑级 interaction tag)

## 模型与 provider

- [ ] Worker 模型性能 A/B 自动比分: 同一 spec 交给 GLM5 / Gemini / MiniMAX, Codex review 谁通过率高谁优先级高
- [x] Provider failover: 某家 API 429/5xx 自动切到备选 ✅ (`OMC_WORKER_FALLBACK_*` 环境变量，worker/auditor 在 primary 抛异常时走 fallback)
- [x] 本地模型接入: 无需改代码，`OMC_WORKER_API_BASE=http://localhost:11434/v1` 即可走 Ollama/vllm；README "Local-model providers" 章节给出配置示例 ✅

## 审计与安全

- [x] 安全审计规则热更新: `OMC_SECRETS_RULES=path/to/rules.json` — `scan_paths` 每次调用自动 re-load，JSON 格式 `[{"name":..., "pattern": regex}, ...]`，无效规则 warn 跳过不中断 ✅ (YAML 延后，JSON 无需外部依赖)
- [ ] 沙箱分级: 普通 worker 只读, Codex 下场有限可写, 只有 accepted 任务才能进入主工作树
- [x] 敏感信息扫描: `omc scan [project_id|--path]` — regex (AWS/OpenAI/Anthropic/JWT/SSH private key/GitHub PAT) + 高熵赋值检查；跳过 node_modules/.venv/dist 等 ✅

## 用户体验

- [ ] Web UI (最基础: project 列表 + task 状态板 + 实时日志)
- [ ] TUI (textual/ratatui) 作为 `omc tmux` 的升级版
- [x] Slack / 企业微信通知: `OMC_NOTIFY_WEBHOOK_URL` 指向任何兼容 `{"text":"..."}` 的 webhook，任务终态 (ACCEPTED/BLOCKED) + 预算 80% 跨线时推送 ✅

## 跨项目与分享

- [x] 全局 `index.sqlite3` 增加统计查询命令 (`omc stats`) ✅ 展示每项目 task 状态计数 + 项目 USD 支出 + 全局汇总
- [x] 项目归档: `omc archive <project_id> [-o out.tar.gz]` — 打包完整 `docs/projects/<id>/` ✅
- [x] 项目导入/导出: `omc import <tarball> [--force]` — 从 tarball 恢复，拒绝绝对路径/`..` 穿越 ✅

## 工程

- [x] 单元测试覆盖率 ≥ 80% ✅ (当前 80%；CI 用 `--cov-fail-under=80` 卡住，回归即挂)
- [x] CI: lint + test + E2E 回归 ✅ (`.github/workflows/ci.yml` 跑 ruff + pytest，`tests/test_e2e_fake.py` 已进默认集，无 `slow` 标记)
- [x] 发布流程: `git tag vX.Y.Z && git push` 触发 `.github/workflows/release.yml` — 构建 wheel+sdist、PyPI trusted publishing、GitHub Release ✅ (brew tap 延后)

## 自举试跑发现的 gap (2026-04-13)

- [x] **`cmd_run` 无自动 seed**: ✅ 补充 `omc task add <project> <task> --path-whitelist`。
- [x] **LiteLLM api_base 歧义**: ✅ `config._normalize_api_base` 剥离 `/chat/completions`/`/completions` 后缀。
- [x] **Codex 跑真实 spec-prompt 极慢**: ✅ 默认 `OMC_CODEX_REASONING_EFFORT=low` + `--ephemeral` + `codex_timeout_s=300`。全局 skills 可由用户 `OMC_CODEX_*` 覆盖。
- [x] **自举尚不完整**: ✅ 新增 `omc plan <project_id>`，Codex 读 `requirement.md` 输出 `[{task_id, brief, path_whitelist}]`，直接 seed 到 sqlite。
- [x] **`docs/projects/**` 不在 `.gitignore`**: ✅ `council.sqlite3` / `workspace/` / `tasks/` / `milestones/` / `reviews/` / `audits/` / `requirement.md` 全部入 `.gitignore`；误提交的历史文件已 `git rm --cached`。
