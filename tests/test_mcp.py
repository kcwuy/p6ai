# -*- coding: utf-8 -*-

import copy
import io
import json
import os
import sqlite3
import tempfile
import unittest

from helpers import build_minimal_db
from p6ai.mcp_server import StdioMcpServer
from p6ai.plan import DEMO_PLAN


def run_server(inputs: str, default_db: str = "") -> list:
    server = StdioMcpServer(default_db=default_db)
    stdout = io.StringIO()
    server.serve(io.StringIO(inputs), stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


class TestMcpProtocol(unittest.TestCase):
    def test_initialize_ping_tools_list(self):
        req = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
            )
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"})
            + "\n"
        )
        msgs = run_server(req)
        self.assertEqual(len(msgs), 3)
        self.assertIn("protocolVersion", msgs[0]["result"])
        self.assertEqual(msgs[0]["result"]["serverInfo"]["name"], "p6ai")
        tools = msgs[1]["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"validate_plan", "create_project", "list_projects", "check_database"})
        self.assertEqual(msgs[2]["result"], {})

    def test_validate_plan_ok(self):
        plan = json.dumps(DEMO_PLAN, ensure_ascii=False)
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "validate_plan", "arguments": {"plan": plan}},
            }
        )
        msgs = run_server(req)
        result = msgs[0]["result"]
        self.assertFalse(result["isError"])
        data = json.loads(result["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["topo_order"]), 4)

    def test_validate_plan_cycle_reports_error(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["relationships"].append(
            {"pred_code": "A1040", "succ_code": "A1010", "type": "PR_FS", "lag_days": 0}
        )
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "validate_plan", "arguments": {"plan": plan}},
            }
        )
        msgs = run_server(req)
        self.assertTrue(msgs[0]["result"]["isError"])

    def test_check_database_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "pmdb.db")
            build_minimal_db(db)
            req = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {"name": "check_database", "arguments": {"db_path": db}},
                }
            )
            msgs = run_server(req)
            result = msgs[0]["result"]
            self.assertFalse(result["isError"])
            data = json.loads(result["content"][0]["text"])
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["friendly_version"], "23.12")

    def test_list_projects_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "pmdb.db")
            build_minimal_db(db)
            conn = sqlite3.connect(db)
            conn.execute("INSERT INTO PROJECT (PROJ_ID, PROJ_SHORT_NAME) VALUES (5, 'XPROJ')")
            conn.commit()
            conn.close()
            req = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {"name": "list_projects", "arguments": {"db_path": db}},
                }
            )
            msgs = run_server(req)
            result = msgs[0]["result"]
            self.assertFalse(result["isError"])
            data = json.loads(result["content"][0]["text"])
            self.assertEqual(data["projects"][0]["proj_short_name"], "XPROJ")

    def test_unknown_tool_and_method(self):
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 14,
                "method": "tools/call",
                "params": {"name": "nope", "arguments": {}},
            }
        )
        msgs = run_server(req)
        self.assertEqual(msgs[0]["error"]["code"], -32602)

        req = json.dumps({"jsonrpc": "2.0", "id": 15, "method": "bogus/method"})
        msgs = run_server(req)
        self.assertEqual(msgs[0]["error"]["code"], -32601)

    def test_exit_notification_stops_server(self):
        req = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "exit"})
            + "\n"
        )
        msgs = run_server(req)
        self.assertEqual(len(msgs), 1)


if __name__ == "__main__":
    unittest.main()
