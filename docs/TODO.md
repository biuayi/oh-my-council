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

- [ ] 失败任务回放: 读 interactions 重演一个任务的完整调用链, 便于 debug
- [ ] diff 审阅 UI (TUI 或 Web): 里程碑验收时 Claude 要 `need_detail` 的场景, 人也能旁听
- [ ] interactions 压缩归档 (超过 N 天的项目迁移到冷存储)

## 预算与观测

- [ ] 预算预警 (非硬停): 到达 80% 时发提醒, 不中断
- [ ] 每日/每周预算汇总报表 (跨项目)
- [ ] 模型调用成本分摊: 按 project / milestone / task 出账

## 模型与 provider

- [ ] Worker 模型性能 A/B 自动比分: 同一 spec 交给 GLM5 / Gemini / MiniMAX, Codex review 谁通过率高谁优先级高
- [ ] Provider failover: 某家 API 429/5xx 自动切到备选
- [ ] 本地模型接入 (Ollama / vllm) 用于安全审计等低敏任务

## 审计与安全

- [ ] 安全审计规则热更新 (YAML 规则库, 不重启 orchestrator)
- [ ] 沙箱分级: 普通 worker 只读, Codex 下场有限可写, 只有 accepted 任务才能进入主工作树
- [ ] 敏感信息扫描 (commit 前 regex + entropy 检查)

## 用户体验

- [ ] Web UI (最基础: project 列表 + task 状态板 + 实时日志)
- [ ] TUI (textual/ratatui) 作为 `omc tmux` 的升级版
- [ ] Slack / 企业微信通知 (里程碑完成 / 需人裁决时提醒)

## 跨项目与分享

- [ ] 全局 `index.sqlite3` 增加统计查询命令 (`omc stats`)
- [ ] 项目归档: 把 `docs/projects/<id>/` 打包成 tarball, 包含完整可重放历史
- [ ] 项目导入/导出: 从别人归档的 tarball 恢复 (用于分享调试样例)

## 工程

- [ ] 单元测试覆盖率 ≥ 80% (MVP 只要求关键模块)
- [ ] CI: lint + test + 一个 E2E 回归 (Fake LLM)
- [ ] 发布流程: 打 tag, 构建 pypi / brew tap
