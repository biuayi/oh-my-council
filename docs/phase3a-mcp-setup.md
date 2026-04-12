# Phase 3a MCP 设置指南

## 前置依赖

安装开发依赖：

```bash
uv sync --extra dev
```

确保 `uv`, Python 3.11+，以及 `tmux`（用于 omc tmux 命令）已安装。

## 注册到 Claude Code

### 方式 1：自动注册（推荐）

```bash
claude mcp add oh-my-council -- uv run omc mcp
```

### 方式 2：手动配置

在 Claude Code 配置文件中添加片段：

```json
{
  "mcpServers": {
    "oh-my-council": {
      "command": "uv",
      "args": ["run", "omc", "mcp"]
    }
  }
}
```

## 可用工具（Tools）

### omc_status
获取项目的任务列表及状态。

**参数：**
- `project_id` (string): 项目 ID

**返回：**
- `project_id`: 项目 ID
- `tasks`: 任务列表，每条任务包含 id、status、attempts、tokens_used

### omc_new
在 docs/projects/ 下创建新项目。

**参数：**
- `slug` (string): 项目简称

**返回：**
- `project_id`: 生成的项目 ID（格式：YYYY-MM-DD-{slug}）
- `root`: 项目根目录路径

### omc_start
运行任务通过模拟管道（仅用于测试）。

**参数：**
- `project_id` (string): 项目 ID
- `task_id` (string): 任务 ID

**返回：**
- `task_id`: 任务 ID
- `status`: 任务最终状态（PENDING、ACCEPTED、BLOCKED 等）

## 可用斜杠命令（Prompts）

六个 MCP 提示词命令：

1. **/omc-new** — 启动新项目，编辑 requirement.md
2. **/omc-plan** — 从 requirement.md 生成任务规范（Phase 3b，暂未实装）
3. **/omc-start** — 运行任务通过模拟管道
4. **/omc-verify** — 里程碑验证（Phase 3b，暂未实装）
5. **/omc-status** — 汇总项目任务状态
6. **/omc-tmux** — 启动观察面板

**Phase 3b 占位命令：**
- `/omc-plan` 和 `/omc-verify` 目前仅返回占位提示。CCB 桥接实装后升级。

## 故障排查

### MCP 服务未响应

在 shell 中手动运行：

```bash
uv run omc mcp
```

此命令会阻塞等待 stdio。若无报错，说明服务正常启动。按 Ctrl+C 退出。

### Claude Code 中 MCP 不出现

检查已注册的 MCP 服务：

```bash
claude mcp list
```

若 oh-my-council 不在列表中，尝试重新注册：

```bash
claude mcp add oh-my-council -- uv run omc mcp
```

### 项目创建失败

确保 `docs/` 目录存在于工作目录，或显式指定 docs 路径。

## 已知限制

- **omc_start**：仅使用模拟管道（FakeCodexClient、FakeWorkerRunner）。实际运行请使用 `omc run` CLI。
- **omc_verify** / **omc_plan**：Phase 3b 后实装，目前不可用。
- **omc tmux**：需要系统安装 tmux 工具。
