# Projects Index Module

## 原始需求

为 oh-my-council 增加一个 projects 索引模块 `src/omc/projects_index.py`，
导出一个函数 `list_projects(docs_root)`，用于扫描 `docs_root/projects/`
下所有子目录（命名约定 `YYYY-MM-DD-<slug>`），返回每个项目的摘要。

## 对 T001 的要求

唯一任务 T001 产出两个文件：

**`src/omc/projects_index.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class ProjectSummary:
    slug: str
    project_id: str       # 目录名 YYYY-MM-DD-<slug>
    path: Path            # 项目目录绝对路径
    has_sqlite: bool      # council.sqlite3 是否存在
    has_requirement: bool # requirement.md 是否存在


def list_projects(docs_root: Path) -> list[ProjectSummary]:
    """List all projects under <docs_root>/projects/.

    Only directories matching pattern 'YYYY-MM-DD-<slug>' are included.
    Returns empty list if projects/ does not exist. Results sorted by
    project_id ascending.
    """
```

实现要求：
- 不存在 `docs_root/projects/` 时返回 `[]`（不抛异常）
- 目录名必须匹配正则 `^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$` 才算项目；不匹配的（例如 `.DS_Store` 或手动建的杂目录）直接跳过
- 从 `project_id` 切出 slug（去掉前 11 个字符 `YYYY-MM-DD-`）
- `has_sqlite` / `has_requirement` 为纯布尔，不读文件内容
- 结果按 `project_id` 升序排列
- 不引入新依赖，只用标准库

**`tests/test_projects_index.py`**

至少覆盖：

1. `test_list_projects_empty_docs_root`：`docs_root/projects/` 不存在时返回 `[]`
2. `test_list_projects_skips_invalid_names`：`projects/` 下有 `.DS_Store`、`random`、`2026-04-12-ok` 三个条目时，只返回 1 条
3. `test_list_projects_detects_sqlite_and_requirement`：两个合法项目，一个有 sqlite + requirement，一个两者都没有，断言字段正确
4. `test_list_projects_sorted_by_project_id`：多个合法项目时按 project_id 升序返回

使用 `pytest` 的 `tmp_path` fixture 构造测试目录；禁止 mock pathlib。

## 路径白名单

T001 只能写以下两个文件（其它路径一律拒绝）：

- `src/omc/projects_index.py`
- `tests/test_projects_index.py`

## 验收

- ruff check 通过
- pytest 新增 4 个测试全部通过
- 不引入任何新依赖
