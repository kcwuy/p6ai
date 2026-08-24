# P6AI

AI 驱动的 **Primavera P6 Professional（独立版 SQLite）计划建库工具**。

> 👥 不熟悉程序的土木行业朋友，请看：[给土木行业朋友的说明](docs/非技术指南.md)

P6AI 接收结构化的施工计划 JSON，先做完整性 / 业务 / 网络（DAG）校验，
再以单事务直接写入 P6 Professional 独立版的 `PPMDBSQLite.db`，自动备份、
自动回滚、自动对齐主键序列。写入后打开 P6 按 **F9** 即可完成进度计算。

> ⚠️ 非官方工具，与 Oracle 无关联。仅面向 P6 Professional **独立版**（SQLite PMDB）。

---

## Features

- 计划校验：字段完整性、WBS 引用、工期合法性、逻辑关系类型、循环依赖检测
- 结构自检：写入前核对数据库表 / 字段是否与当前 P6 版本兼容，防止误写 EPPM 库
- 安全写入：自动备份 + 单事务 + 失败整体回滚 + `NEXTKEY` 主键序列对齐
- 版本适配：针对 P6 Professional 23.12 独立版真实表结构编写（含 22 位 GUID、EPS 挂接）
- 无第三方运行时依赖（仅 Python 标准库）

## Quick Start

```bash
# 1. 结构自检：确认目标库与本工具兼容
python -m p6ai check --db "C:\Users\<you>\Documents\PPMDBSQLite.db"

# 2. 校验计划 JSON（不写库）
python -m p6ai validate --plan plan.json

# 3. 写入 P6 数据库（自动备份）
python -m p6ai create --plan plan.json --db "C:\Users\<you>\Documents\PPMDBSQLite.db"

# 4. 打开 P6 Professional，打开新项目，按 F9 进度计算
```

## Plan JSON Format

```json
{
  "project_code": "PRJ-2026-001",
  "project_name": "某变电站土建及机电安装工程",
  "start_date": "2026-09-01 08:00:00",
  "calendar_name": "Corporate - Standard Full Time",
  "wbs_tree": [
    { "wbs_code": "WBS.1", "wbs_name": "土建工程", "parent": null },
    { "wbs_code": "WBS.1.1", "wbs_name": "桩基与地基处理", "parent": "WBS.1" }
  ],
  "tasks": [
    { "task_code": "A1010", "task_name": "场地平整及放线", "wbs_code": "WBS.1.1", "duration_days": 5 },
    { "task_code": "A1020", "task_name": "静压管桩施工及检测", "wbs_code": "WBS.1.1", "duration_days": 12.5 }
  ],
  "relationships": [
    { "pred_code": "A1010", "succ_code": "A1020", "type": "PR_FS", "lag_days": 0 }
  ]
}
```

- 逻辑关系类型：`PR_FS` / `PR_SS` / `PR_FF` / `PR_SF`
- `duration_days` 可为小数，必须大于 0
- 全网必须是有向无环图（DAG），禁止循环

## Safety Notes

- 写入期间必须**完全关闭 P6 Professional**（数据库被占用时会拒绝写入并提示）
- 每次写入前自动生成 `PPMDBSQLite.db.bak_时间戳` 备份
- 写入基于逆向验证的表结构，不同 P6 版本请先运行 `check`

## MCP 接口（AI 工具）

p6ai 内置一个**零依赖**的 MCP 服务器（stdio 传输，仅使用 Python 标准库），
任何支持 MCP 的 AI 客户端（Claude Desktop、Codex、Cursor 等）都可以直接调用：

| 工具 | 说明 |
|---|---|
| `validate_plan` | 校验计划 JSON（字段、WBS 引用、工期、关系类型、循环依赖） |
| `create_project` | 校验并写入 P6 数据库（自动备份、单事务、失败回滚） |
| `list_projects` | 只读列出数据库中的项目 |
| `check_database` | 数据库结构自检与版本识别 |

启动服务器：

```bash
python -m p6ai serve
# 安装后也可直接：p6ai serve
```

Claude Desktop 配置示例（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "p6ai": {
      "command": "python",
      "args": ["-m", "p6ai", "serve"],
      "cwd": "C:\\path\\to\\p6ai"
    }
  }
}
```

Codex CLI 配置示例（`~/.codex/config.toml`）：

```toml
[mcp_servers.p6ai]
command = "python"
args = ["-m", "p6ai", "serve"]
cwd = "C:\\path\\to\\p6ai"
```

> 如果 `python` 不在系统 PATH 中，请把 `command` 换成 Python 解释器的完整路径。
> AI 客户端可以直接用自然语言驱动这些工具，例如："校验这份计划"、"把这个施工方案
> 建到 P6 里"。

## Supported Environments

- Primavera P6 Professional 23.12（独立版 SQLite，`PPMDB,2312.*`）
- Python 3.9+

## Roadmap

- [x] MCP 服务器：向 AI 客户端（Claude / Codex / Cursor）暴露校验、建库、列表、自检工具
- [ ] XER 导出与 DCMA 质检集成
- [ ] 多版本 schema 适配层

## License

MIT

## Disclaimer

本工具为社区项目，与 Oracle Corporation 及其产品无任何关联或背书。
使用直接写入数据库的方式操作 P6 数据存在风险，请务必自行备份并在测试环境验证后使用。
