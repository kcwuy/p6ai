# -*- coding: utf-8 -*-
"""
零依赖 MCP（Model Context Protocol）服务器。

通过标准输入/输出（stdio）与任何支持 MCP 的 AI 客户端通信，
向 AI 暴露以下工具：
  - validate_plan     校验计划 JSON
  - create_project    校验并把计划写入 P6 数据库（自动备份）
  - list_projects     列出 P6 数据库中的项目
  - check_database    P6 数据库结构自检

运行：python -m p6ai serve
"""

import json
import sys
import traceback

from . import __version__
from .plan import validate_plan_data
from .schema import check_database
from .writer import DEFAULT_DB, create_p6_project, list_projects


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "p6ai"


TOOL_DEFS = [
    {
        "name": "validate_plan",
        "description": (
            "校验 P6 计划 JSON：字段完整性、WBS 引用、工期合法性、"
            "逻辑关系类型、循环依赖检测。plan 可以是 JSON 对象或 JSON 字符串。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {
                    "description": (
                        "P6 计划数据：project_code / project_name / start_date / "
                        "calendar_name / wbs_tree / tasks / relationships"
                    ),
                    "oneOf": [{"type": "object"}, {"type": "string"}],
                }
            },
            "required": ["plan"],
        },
    },
    {
        "name": "create_project",
        "description": (
            "校验计划并直接写入 P6 Professional 独立版 SQLite 数据库。"
            "自动备份、单事务、失败整体回滚。写入期间请确保 P6 已完全关闭。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan": {
                    "description": "P6 计划数据（格式同 validate_plan）",
                    "oneOf": [{"type": "object"}, {"type": "string"}],
                },
                "db_path": {
                    "type": "string",
                    "description": "P6 数据库文件路径，缺省使用默认路径",
                },
                "backup": {
                    "type": "boolean",
                    "description": "写入前是否自动备份，默认 true",
                },
            },
            "required": ["plan"],
        },
    },
    {
        "name": "list_projects",
        "description": "只读列出 P6 数据库中的项目（ID、代码、计划起止、工序/WBS 数量）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_path": {
                    "type": "string",
                    "description": "P6 数据库文件路径，缺省使用默认路径",
                }
            },
        },
    },
    {
        "name": "check_database",
        "description": (
            "对 P6 数据库执行结构自检：SQLite 格式、版本识别、"
            "表/字段兼容性、EPPM 特征检测、是否被占用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_path": {
                    "type": "string",
                    "description": "P6 数据库文件路径，缺省使用默认路径",
                }
            },
        },
    },
]


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    raise ValueError("plan 参数必须是 JSON 对象或 JSON 字符串")


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


class StdioMcpServer:
    """使用 Python 标准库实现的 MCP stdio 服务器。"""

    def __init__(self, default_db: str = DEFAULT_DB):
        self.default_db = default_db
        self.tools = {t["name"]: t for t in TOOL_DEFS}
        self._shutdown = False

    # ---------- JSON-RPC 基础 ----------
    @staticmethod
    def _jsonrpc(msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _jsonrpc_error(msg_id, code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # ---------- 协议分发 ----------
    def handle_message(self, msg):
        """处理一条 JSON-RPC 消息；通知返回 None。"""
        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "exit":
            self._shutdown = True
            return None

        if msg_id is None:
            # 通知（如 notifications/initialized）：无需响应
            return None

        try:
            if method == "initialize":
                return self._jsonrpc(
                    msg_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": __version__},
                    },
                )
            if method == "ping":
                return self._jsonrpc(msg_id, {})
            if method == "tools/list":
                return self._jsonrpc(msg_id, {"tools": list(self.tools.values())})
            if method == "tools/call":
                return self._handle_tools_call(msg_id, msg.get("params") or {})
            if method == "shutdown":
                return self._jsonrpc(msg_id, {})
            return self._jsonrpc_error(msg_id, -32601, f"未知方法: {method}")
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return self._jsonrpc_error(msg_id, -32603, f"服务器内部错误: {e}")

    def _handle_tools_call(self, msg_id, params):
        name = params.get("name")
        if name not in self.tools:
            return self._jsonrpc_error(msg_id, -32602, f"未知工具: {name}")
        args = params.get("arguments") or {}
        try:
            text, is_error = self._dispatch(name, args)
            return self._jsonrpc(
                msg_id,
                {"content": [{"type": "text", "text": text}], "isError": is_error},
            )
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return self._jsonrpc_error(msg_id, -32603, f"工具执行失败: {e}")

    # ---------- 工具实现 ----------
    def _dispatch(self, name, args):
        if name == "validate_plan":
            return self._tool_validate_plan(args)
        if name == "create_project":
            return self._tool_create_project(args)
        if name == "list_projects":
            return self._tool_list_projects(args)
        if name == "check_database":
            return self._tool_check_database(args)
        raise ValueError(f"未知工具: {name}")

    def _tool_validate_plan(self, args):
        try:
            plan = _as_dict(args.get("plan"))
        except (ValueError, json.JSONDecodeError) as e:
            return json.dumps({"ok": False, "message": f"plan 参数无效: {e}"}, ensure_ascii=False), True
        ok, msg, order = validate_plan_data(plan)
        return json.dumps({"ok": ok, "message": msg, "topo_order": order}, ensure_ascii=False), not ok

    def _tool_create_project(self, args):
        try:
            plan = _as_dict(args.get("plan"))
        except (ValueError, json.JSONDecodeError) as e:
            return json.dumps({"ok": False, "message": f"plan 参数无效: {e}"}, ensure_ascii=False), True
        db_path = args.get("db_path") or self.default_db
        backup = _as_bool(args.get("backup"), True)
        result = create_p6_project(db_path, plan, backup=backup)
        return json.dumps(result, ensure_ascii=False), result["status"] != "success"

    def _tool_list_projects(self, args):
        db_path = args.get("db_path") or self.default_db
        result = list_projects(db_path)
        return json.dumps(result, ensure_ascii=False), result["status"] != "success"

    def _tool_check_database(self, args):
        db_path = args.get("db_path") or self.default_db
        report = check_database(db_path)
        return json.dumps(report, ensure_ascii=False), report["status"] != "ok"

    # ---------- stdio 主循环 ----------
    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        try:
            stdin.reconfigure(encoding="utf-8", errors="replace")
            stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                self._write(stdout, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"解析错误: {e}"}})
                continue
            try:
                resp = self.handle_message(msg)
            except Exception:
                resp = self._jsonrpc_error(msg.get("id"), -32603, "服务器内部错误")
            if resp is not None:
                if not self._write(stdout, resp):
                    return
            if self._shutdown:
                return

    @staticmethod
    def _write(stdout, obj) -> bool:
        try:
            stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            stdout.flush()
            return True
        except (BrokenPipeError, OSError):
            return False
