# oh-my-council 设计稿 (MVP = β)

- 日期: 2026-04-12
- 状态: draft (待 writing-plans 转实施计划)
- 作者: Hertz + Claude (brainstorming 阶段)

## 0. 目标与非目标

**目标**: 构建一个多 agent 协作工具，让廉价模型 (GLM5/Gemini/MiniMAX) 承担主力编码，Codex 承担技术经理职责 (规格设计 + code review + 安全审计 + 失败下场),
Claude 仅在需求定义、里程碑验收、失败裁决三个关键点短暂介入，以**极大降低 Claude token 消耗**。

**显式非目标 (MVP 阶段)**:
- 不做 Web UI 或图形报表
- 不做跨项目并行调度
- 不做 context 压缩机制的实际运行 (只保留 schema, γ 再做)
- 不做 worker 模型性能自动比分

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Code 会话 (UX 入口, 冷启动、最小上下文)                │
│    slash commands:                                           │
│      /omc new       → 启动需求澄清 (brainstorming skill)     │
│      /omc plan      → 触发 Codex 对齐 (co-brainstorm)        │
│      /omc start     → 把任务写入 sqlite, orchestrator 接管    │
│      /omc verify    → 里程碑短调用验收                        │
│      /omc status    → 读 sqlite 生成汇报                      │
│      /omc tmux      → 起观察面板                              │
└─────────────────────────────────────────────────────────────┘
                              │ MCP
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  omc-orchestrator (Python 常驻进程 / 按需起)                  │
│  ├─ CCB  (Claude-Codex-Bridge): PM↔TechLead 会话桥           │
│  ├─ Dispatcher: 任务状态机 + 并发池                           │
│  ├─ CodexClient: Codex CLI 子进程封装 (spec / review / 下场) │
│  ├─ WorkerRunner: LiteLLM → GLM5/Gemini/MiniMAX              │
│  ├─ Gatekeeper: 编译门禁 / 幻觉门禁 / 路径白名单              │
│  ├─ Auditor: GLM5 安全扫描                                    │
│  ├─ Budgeter: L1-L4 预算硬线                                  │
│  └─ Store: sqlite + MD 落盘                                   │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 关键设计决策 (brainstorming 过程记录)

| # | 决策 | 理由 |
|---|---|---|
| Q1 | 架构形态 = **C 混合**: Claude Code plugin 作 UX 入口 + 外部 orchestrator 跑长循环 | 同时满足"低 Claude token"和"保留交互体验" |
| Q2 | Worker 粒度 = **A 文件级**, 复杂模块降到 B 函数级 | 文件路径由 spec 钉死, worker 不越界; 可重试可控 |
| Q3 | Codex 调用 = **A Codex CLI 子进程** + 允许下场模式 | 复用 Codex 现有 sandbox/approval; worker 失败时 Codex 可亲自改文件 |
| Q4 | Claude 调用 = **D 变体**: Claude Code 会话只做入口 + 里程碑验收, orchestrator 全程接管长循环 | Claude Code 会话与 Claude agent 调用账本分开, token 按里程碑数线性增长而非任务数 |
| Q5 | 持久化切分: **MD** 承载需求/设计/TODO/实现流程; **sqlite** 承载 agent 间交互 + 压缩 checkpoint + 任务状态机索引 | 人类可读与机器高频读写分离; MD 可 git diff |
| Q6 | 验收闭环 = **D 分层**: 单任务 Codex+GLM5 闭环不打扰 Claude; 里程碑级 Claude 短调用验收; 单任务连续失败升级 Codex 下场, 仍失败再升级 Claude | 任务数与 Claude 调用数解耦 |
| Q7 | 硬线: L1=3 / L2=1 / L3=200k / L4=$5; 无日预算; **幻觉门禁强制** | 通过幻觉门禁堵住大类错误 |
| Q8 | MVP = **β**; γ 功能写入 `docs/TODO.md` | 第一版必须端到端可用, 但避免范围蔓延 |

### 1.2 术语

- **CCB (Claude-Codex-Bridge)**: orchestrator 中专门承载 "PM↔TechLead" 交互的子模块 (区别于 Codex↔Workers 的 Dispatcher)
- **下场模式 (escalation to Codex)**: Worker 连续失败达阈值后, Codex CLI 以可写 sandbox 身份接管该任务
- **里程碑 (milestone)**: 一组有依赖关系的任务的集合, 整体完成后触发 Claude 短调用验收
- **Gatekeeper**: 编译/幻觉/路径 三门禁的总称, 任务产出必须全部通过才能进入 review
- **幻觉门禁 (hallucination gate)**: 强制要求 Codex review 时产出"引用符号验证清单" (每个 import/调用的符号都 grep 代码库或 package manifest 确认存在), 未通过视同 reject

## 2. 角色分工

| 角色 | 模型 | 调用方式 | 职责 |
|---|---|---|---|
| PM | Claude | Claude Code 会话 + `claude -p` 短调用 | 需求澄清、任务拆分、里程碑验收、升级裁决 |
| TechLead | Codex (gpt-5-codex) | Codex CLI 子进程 | 产出文件级 spec、code review (含幻觉门禁)、失败时下场重写 |
| Worker | GLM5 主力 / Gemini / MiniMAX 备选 | LiteLLM 库 (in-process) | 按 spec 填代码 (文件级, 复杂模块降到函数级) |
| Auditor | GLM5 | LiteLLM 库 | 安全扫描 (注入/硬编码密钥/命令执行/路径穿越) |

Claude Code 会话与 Claude agent 调用是两套账本:
- **Claude Code 会话**: 用户交互 UX, 不跑长循环
- **Claude agent 调用**: orchestrator 通过 `claude -p` 非交互模式起的短命进程, 每次冷启动, 只从 sqlite 读必要切片

## 3. 单任务生命周期

```
pending
  → Codex produces spec (文件级, 含签名/伪代码/期望符号清单)
  → running (Worker via LiteLLM 写代码)
  → Gatekeeper.path_whitelist (worker 只能写 spec 里钉死的路径; 越界直接丢弃)
  → Gatekeeper.syntax (本地 ruff/tsc/go vet; fail 退回 pending, 计入 L1)
  → Codex review (幻觉门禁强制; fail 退回 pending, 计入 L1)
  → Auditor (GLM5 安全扫描; fail → Codex 下场修复)
  → accepted (落盘到 tasks/<id>.md, 更新 sqlite.tasks)

失败升级路径:
  L1 超限 (worker 重试 >3) → Codex 下场模式 (CLI exec, 可写 sandbox)
  L2 超限 (Codex 下场仍 fail)  → 标记 blocked, 等里程碑触发时升级 Claude
  L3 超限 (单任务 token >200k) → 强制停止, 标记 over_budget, 升级 Claude
```

## 4. 里程碑验收

- Claude 在 `/omc new` 阶段就把任务按依赖切成若干 milestone (或让 Claude 自动推断)
- orchestrator 跑完一个 milestone 的全部任务后, 触发 `claude -p` 短调用
- 输入: 该 milestone 所有任务的**精简摘要 JSON** (`id / files / 一句话意图 / Codex review 结论 / 审计结论`), 不含任何原文代码
- 输出: `accept_milestone | reject_tasks=[T003,T007] | need_detail=T005`
- `need_detail` 时 orchestrator 再把对应任务详情塞给 Claude 做第二次短调用
- `reject_tasks` 会把这些任务回退到 `pending` 并 Codex 重出 spec

## 5. 持久化

### 5.1 docs/ 目录布局

```
docs/
├── index.sqlite3                    # 全局 projects 索引 (跨项目查询用, MVP 只维护基本字段)
├── TODO.md                          # γ 延后功能清单
├── superpowers/
│   └── specs/                       # brainstorming skill 产出
│       └── 2026-04-12-oh-my-council-design.md
└── projects/
    └── 2026-04-12-<slug>/
        ├── council.sqlite3          # 本 project 主库 (3 张表)
        ├── requirement.md           # 原始需求 (用户原话 + 澄清摘要)
        ├── design/
        │   ├── architecture.md      # Codex 产出的架构设计
        │   └── milestones.md        # Claude 产出的里程碑切分
        ├── todo.md                  # 任务清单 (人类可读, 与 sqlite.tasks 保持同步)
        ├── implementation.md        # 实现流程记录 (跑完后总结写入)
        ├── tasks/
        │   └── T001-<slug>.md       # 每任务一文件 (spec + 文件白名单 + review 摘要)
        ├── reviews/
        │   └── T001.md              # Codex review 原文 (含幻觉门禁清单)
        ├── audits/
        │   └── T001.md              # GLM5 安全审计原文
        └── artifacts/               # worker 产出的代码副本 (主拷贝在项目源码位置, 这里是归档)
```

### 5.2 sqlite schema

**`index.sqlite3`** (全局):
```sql
CREATE TABLE projects (
    id          TEXT PRIMARY KEY,        -- e.g. 2026-04-12-<slug>
    title       TEXT NOT NULL,
    status      TEXT NOT NULL,           -- planning | running | paused | done | aborted
    root_path   TEXT NOT NULL,           -- docs/projects/<id>
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

**`council.sqlite3`** (每个 project 一份):

```sql
-- 表1: 任务状态机索引 (任务正文仍在 MD)
CREATE TABLE tasks (
    id            TEXT PRIMARY KEY,       -- T001, T002, ...
    project_id    TEXT NOT NULL,
    milestone_id  TEXT,
    md_path       TEXT NOT NULL,          -- tasks/T001-<slug>.md
    status        TEXT NOT NULL,          -- pending|running|review|audit|blocked|accepted|over_budget
    assignee      TEXT,                   -- glm5|gemini|minimax|codex (下场时)
    attempts      INTEGER NOT NULL DEFAULT 0,
    codex_escalated INTEGER NOT NULL DEFAULT 0,
    tokens_used   INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    path_whitelist TEXT NOT NULL,         -- JSON: 允许写入的路径列表
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- 表2: agent 之间/agent 与模型之间的所有交互
CREATE TABLE interactions (
    id          INTEGER PRIMARY KEY,
    project_id  TEXT NOT NULL,
    task_id     TEXT,                     -- 可空 (项目级消息, 如里程碑验收)
    from_agent  TEXT NOT NULL,            -- claude|codex|glm5|gemini|orchestrator
    to_agent    TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- request|response|review|audit|handoff|escalation
    content     TEXT NOT NULL,            -- JSON 或文本原文
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    created_at  TEXT NOT NULL
);

-- 表3: context 压缩前的快照 (MVP 建表不强制用)
CREATE TABLE compression_checkpoints (
    id            INTEGER PRIMARY KEY,
    project_id    TEXT NOT NULL,
    task_id       TEXT,
    agent         TEXT NOT NULL,
    reason        TEXT,                   -- approaching_ctx_limit|task_boundary|manual
    summary       TEXT NOT NULL,
    carry_forward TEXT NOT NULL,          -- JSON: 必须保留的关键事实
    dropped_refs  TEXT,                   -- JSON: 被丢弃但可回查的 MD 路径
    created_at    TEXT NOT NULL
);
```

### 5.3 MD 与 sqlite 的一致性

- MD 为真实来源 (source of truth) 对于: 需求、设计、任务正文、review/audit 原文
- sqlite 为真实来源对于: 任务状态、attempt 计数、预算消耗、interactions 历史
- `tasks.md_path` 是 sqlite 指向 MD 的外键; `tasks.status` 不在 MD 里存 (避免并发写 MD 冲突)

## 6. 硬线与门禁

### 6.1 预算硬线

| # | 硬线 | 默认值 | 触发动作 |
|---|---|---|---|
| L1 | 单任务 worker 重试次数 | 3 | 超限 → Codex 下场 |
| L2 | 单任务 Codex 下场重试 | 1 | 超限 → status=blocked, 里程碑时升级 Claude |
| L3 | 单任务 token 预算 (所有模型合计) | 200k | 超限 → status=over_budget, 升级 Claude |
| L4 | 项目总预算 | $5 | 超限 → orchestrator 暂停所有任务, 等人确认 |

无"每日预算"(按用户决策)。

### 6.2 质量门禁 (Gatekeeper)

1. **编译/语法**: 按项目类型选 `ruff/tsc --noEmit/go vet/...`, 在 worker 产出后 orchestrator 本地跑; fail 不占 Codex review 次数, 但占 L1 计数。
2. **幻觉门禁 (强制)**: Codex review prompt 要求逐个列出代码引用的 import / 类 / 函数 / 外部 API, 并标注"已验证存在 (路径/行号)"或"未验证"; 任何"未验证"项 = reject。
3. **路径白名单**: worker 产出的文件路径必须在 `tasks.path_whitelist` 集合内, 越界写入 orchestrator 直接丢弃, 不落盘, 不进入 review, 计入 L1。

### 6.3 测试门禁 (若 spec 要求写测试)

pytest/jest/go test 失败 = review reject, 计入 L1。

## 7. tmux 观察面板

`omc tmux` 起 5 pane:

| pane | 内容 |
|---|---|
| 1 | 你的 Claude Code 会话 (入口 + 汇报) |
| 2 | `omc tail` — orchestrator 主日志 (任务流转) |
| 3 | `omc tail --worker` — 当前 worker 实时 stdout |
| 4 | `omc watch-db` — `watch -n 1 'sqlite3 council.sqlite3 "SELECT id,status,assignee FROM tasks"'` |
| 5 | `omc tail --review` — Codex review / 安全审计流 |

## 8. MVP (β) 交付清单

- [ ] MCP server (`oh-my-council`) + slash commands: new/plan/start/verify/status/tmux
- [ ] orchestrator 主循环 + 并发池 (默认 2 个 worker)
- [ ] sqlite 3 张表 + MD 落盘 + 全局 index
- [ ] CodexClient (spec / review / 下场三种模式)
- [ ] WorkerRunner (LiteLLM, 默认 GLM5, 可配 Gemini/MiniMAX)
- [ ] Gatekeeper (编译 + 幻觉 + 路径白名单)
- [ ] Auditor (GLM5 安全扫描)
- [ ] Budgeter (L1-L4 硬线)
- [ ] 里程碑级 `claude -p` 短调用验收
- [ ] `omc tmux` 观察面板
- [ ] 端到端 E2E: 1 个真实小需求生成 1 个 Python 文件 + 1 个测试, 全流程跑通

## 9. γ 延后功能

详见 `docs/TODO.md`。关键项:
- compression_checkpoints 真正生效
- 跨项目统计与 Web UI
- 失败任务回放 / diff 审阅 UI
- 多项目并行调度
- 预算预警 (非硬停)
- Worker 模型性能 A/B 自动比分
- 审计规则热更新

## 10. 测试策略

- **单元**: Gatekeeper 各门禁、Budgeter L1-L4、Store (sqlite + MD 往返一致性)
- **集成**: Fake LLM provider (确定性输出 + 可注入失败) 跑完整单任务 pipeline
- **E2E** (MVP 必须过): 用一个真实小需求跑通 —— 生成 1 个 Python 文件 + 1 个 pytest 文件, 全程 L1 内通过, 里程碑验收 accept

## 10.5 Credentials

Secrets MUST live outside the repo. Canonical location: `~/.config/oh-my-council/.env` (mode 0600).
Expected keys (Phase 2+):

- `OMC_WORKER_VENDOR` — `minimax` | `zhipu` | `google` | `openai` (LiteLLM provider prefix)
- `OMC_WORKER_MODEL` — concrete model id, e.g. `MiniMax-M2.5`, `glm-4-plus`, `gemini-2.5-flash`
- `OMC_WORKER_API_BASE` — vendor endpoint URL
- `OMC_WORKER_API_KEY` — secret
- (future) `OMC_AUDITOR_*`, `OMC_CODEX_*` blocks

**Never** commit secrets. `.gitignore` covers `.worktrees/` but never extend it to cover `src/` or `docs/` for secret-holding files — secrets belong entirely outside the repo.

MVP testing vendor (as of 2026-04-12): **MiniMax (`MiniMax-M2.5`)** via `api.minimaxi.com`. Other vendors (Zhipu GLM, Gemini) plug in by swapping env vars; WorkerRunner is vendor-agnostic via LiteLLM.

## 11. 风险与开放问题

- **Codex CLI 非官方输出格式稳定性**: 需要包装层解析, 可能随 Codex 版本变化。缓解: 封装在 `CodexClient` 一个模块内, 版本变化只改这里。
- **幻觉门禁的误报率**: Codex 可能把真实符号标成"未验证"导致无限 reject。缓解: L1 触顶后自动升级 Codex 下场, 不会死循环。
- **LiteLLM 对国产模型 (GLM/MiniMAX) 的支持成熟度**: 若某 provider 不稳, orchestrator 要能快速切换。WorkerRunner 需要提供 `--model` 覆盖。
- **`claude -p` 非交互调用的可靠性与输出解析**: 第一版用 JSON 模式输出, 失败重试 1 次, 再失败标 blocked 等人。
- **跨 session 的一致性**: Claude Code 会话结束后 orchestrator 继续跑, 你再开新会话看结果 —— 必须 100% 走 sqlite/MD, 绝不依赖会话内存。
