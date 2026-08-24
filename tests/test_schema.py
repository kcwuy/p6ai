# -*- coding: utf-8 -*-

import os
import sqlite3
import tempfile
import unittest

from p6ai.schema import check_database, is_sqlite_file


def build_minimal_db(path, with_epmm_marker=False):
    """按 REQUIRED_TABLES 构造一个最小兼容库（用于测试自检）。"""
    from p6ai.schema import REQUIRED_TABLES

    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for table, cols in REQUIRED_TABLES.items():
        col_defs = ", ".join(f"{c} TEXT" for c in cols)
        cur.execute(f"CREATE TABLE {table} ({col_defs})")
    cur.execute("CREATE TABLE PREFER (DATABASE_VERSION TEXT, MIN_PRO_VERSION TEXT)")
    cur.execute("INSERT INTO PREFER VALUES ('PPMDB,2312.0000.0000.0005', '23.10.00')")
    if with_epmm_marker:
        cur.execute("ALTER TABLE PROJECT ADD COLUMN STATUS_CODE TEXT")
    conn.commit()
    conn.close()


class TestSchemaCheck(unittest.TestCase):
    def test_is_sqlite_file(self):
        self.assertTrue(is_sqlite_file(os.path.join(os.environ["TEMP"], "p6inspect", "PPMDBSQLite.db")))

    def test_missing_file(self):
        report = check_database(r"C:\no\such\file.db", probe_lock=False)
        self.assertEqual(report["status"], "error")
        self.assertFalse(report["exists"])

    def test_compatible_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pmdb.db")
            build_minimal_db(path)
            report = check_database(path, probe_lock=False)
            self.assertEqual(report["status"], "ok", report["message"])
            self.assertTrue(report["compatible"])
            self.assertEqual(report["friendly_version"], "23.12")

    def test_missing_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pmdb.db")
            build_minimal_db(path)
            conn = sqlite3.connect(path)
            conn.execute("DROP TABLE TASK")
            conn.commit()
            conn.close()
            report = check_database(path, probe_lock=False)
            self.assertEqual(report["status"], "incompatible")
            self.assertIn("TASK", report["missing_tables"])

    def test_epmm_marker_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pmdb.db")
            build_minimal_db(path, with_epmm_marker=True)
            report = check_database(path, probe_lock=False)
            self.assertEqual(report["status"], "incompatible")
            self.assertIn("STATUS_CODE", report["epmm_markers"]["PROJECT"])


if __name__ == "__main__":
    unittest.main()
