# Phase 3c — USD 预算追踪 Runbook

## 背景

- L4 = **$5 USD / 项目** 硬线（spec §Q7）。
- 单次 worker/auditor/codex 调用的实际花销由 `src/omc/pricing.py` 的价格表计算后写入 `interactions.cost_usd`，聚合到 `tasks.cost_usd` 与项目级 `SUM(cost_usd)`。
- 超过 L4 时 Dispatcher 把当前任务转为 `over_budget` 并退出。

## 价格表

默认值位于 `src/omc/pricing.py::DEFAULT_PRICES`（USD / 1M tokens, in/out）。覆盖方式：

1. `~/.config/oh-my-council/prices.toml`（0600）
2. 格式：

```toml
[prices."minimax-text-01"]
in_usd_per_mtok = 0.20
out_usd_per_mtok = 1.10

[prices."glm-4.6"]
in_usd_per_mtok = 0.60
out_usd_per_mtok = 2.20
```

3. 未在表中的模型 → 记 0 成本（不会报错，仅不计入预算）。建议新模型先试跑，确认 token 用量后再加入表。

## 查看当前花销

### CLI

```bash
omc budget <slug>
```

输出样例：

```
project: demo-refactor  (id=2026-04-12-demo-refactor)
spend:   $0.7342  /  limit $5.00  (L4)
by agent:
  glm5           $0.5021
  codex          $0.2000
  orchestrator   $0.0321
remaining: $4.2658
```

退出码：`0` = 正常，`2` = 项目不存在。

### MCP / slash

Claude Code 会话里：`/omc_budget <slug>`，会调用 `omc_budget` 工具返回结构化 dict。

## L4 触发行为

1. 每个 worker/auditor/review 调用后检查 `BudgetTracker.l4_exhausted()`。
2. 超线立即 `BUDGET_EXCEEDED` 事件，任务状态机转 `OVER_BUDGET`。
3. 其它任务不会自动停止 — 需要人工介入。后续 γ 考虑整体 abort。

## 不在 Phase 3c 范围

- Codex CLI 子进程的 token 目前返回 0（Codex CLI 还未暴露 usage），γ 再解决。
- Claude `-p` 调用计费走 Anthropic API 账本，本地表只作参考。
- 没有日/周 budget — 只有项目级 L4。
- 没有通知/报警 — 仅退出码 + 状态。

## 故障排查

| 症状 | 可能原因 |
|---|---|
| `spend=0` 但确认有调用 | 模型名未在价格表中；检查 `OMC_WORKER_MODEL` 与 `prices.toml` |
| 任务突然 `over_budget` | 确认 `prices.toml` 不是小数点错放（0.2 vs 2.0） |
| `omc budget` 找不到项目 | slug 没匹配到 `docs/projects/YYYY-MM-DD-<slug>/` 目录 |
