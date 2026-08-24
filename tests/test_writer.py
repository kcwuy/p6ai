# -*- coding: utf-8 -*-

import os
import sqlite3
import tempfile
import unittest

from helpers import build_functional_db
from p6ai.plan import DEMO_PLAN
from p6ai.writer import create_p6_project


class TestCreateProject(unittest.TestCase):
    def test_create_project_on_functional_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "pmdb.db")
            build_functional_db(db)
            result = create_p6_project(db, DEMO_PLAN)
            self.assertEqual(result["status"], "success", result["message"])
            self.assertEqual(result["project_id"], 2)
            self.assertEqual(result["counts"], {"wbs": 6, "tasks": 4, "relationships": 3})

            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            proj = cur.execute("SELECT * FROM PROJECT WHERE PROJ_ID = 2").fetchone()
            orig_proj_id = proj["ORIG_PROJ_ID"]
            short_name = proj["PROJ_SHORT_NAME"]
            root = cur.execute(
                "SELECT PARENT_WBS_ID FROM PROJWBS WHERE PROJ_ID = 2 AND PROJ_NODE_FLAG = 'Y'"
            ).fetchone()
            parent_wbs_id = root["PARENT_WBS_ID"]
            next_proj = cur.execute("SELECT KEY_SEQ_NUM FROM NEXTKEY WHERE KEY_NAME = 'project_proj_id'").fetchone()[0]
            next_task = cur.execute("SELECT KEY_SEQ_NUM FROM NEXTKEY WHERE KEY_NAME = 'task_task_id'").fetchone()[0]
            conn.close()

            self.assertIsNone(orig_proj_id)
            self.assertEqual(short_name, "PRJ-TEST-001")
            self.assertEqual(int(parent_wbs_id), 1)
            self.assertEqual(int(next_proj), 3)
            self.assertEqual(int(next_task), 5)

    def test_create_project_rejects_invalid_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "pmdb.db")
            build_functional_db(db)
            bad_plan = dict(DEMO_PLAN)
            bad_plan["tasks"] = []
            result = create_p6_project(db, bad_plan)
            self.assertEqual(result["status"], "error")
            self.assertIn("数据校验失败", result["message"])


if __name__ == "__main__":
    unittest.main()
