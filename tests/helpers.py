# -*- coding: utf-8 -*-
"""测试用数据库构造工具。"""

import sqlite3

from p6ai.schema import REQUIRED_TABLES


def build_minimal_db(path, with_epmm_marker=False):
    """按 REQUIRED_TABLES 构造一个最小兼容库（用于测试自检）。"""
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        for table, cols in REQUIRED_TABLES.items():
            col_defs = ", ".join(f"{c} TEXT" for c in cols)
            cur.execute(f"CREATE TABLE {table} ({col_defs})")
        cur.execute("CREATE TABLE PREFER (DATABASE_VERSION TEXT, MIN_PRO_VERSION TEXT)")
        cur.execute("INSERT INTO PREFER VALUES ('PPMDB,2312.0000.0000.0005', '23.10.00')")
        if with_epmm_marker:
            cur.execute("ALTER TABLE PROJECT ADD COLUMN STATUS_CODE TEXT")
        conn.commit()
    finally:
        conn.close()


def build_functional_db(path):
    """构造可执行完整建库流程的最小 P6 兼容库（含日历、OBS、EPS 根）。"""
    build_minimal_db(path)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO CALENDAR (CLNDR_ID, CLNDR_NAME, CLNDR_TYPE, DAY_HR_CNT, DEFAULT_FLAG) "
            "VALUES (1, 'Corporate - Standard Full Time', 'CA_Base', 8.0, 'Y')"
        )
        cur.execute(
            "INSERT INTO OBS (OBS_ID, PARENT_OBS_ID, OBS_NAME) VALUES (1, NULL, 'None')"
        )
        cur.execute(
            "INSERT INTO PROJECT (PROJ_ID, PROJ_SHORT_NAME, PROJECT_FLAG, CLNDR_ID, GUID) "
            "VALUES (1, 'EPS', 'N', 1, 'abcdefghijklmnopqrstuv')"
        )
        cur.execute(
            "INSERT INTO PROJWBS (WBS_ID, PROJ_ID, PARENT_WBS_ID, OBS_ID, SEQ_NUM, EST_WT, "
            "PROJ_NODE_FLAG, SUM_DATA_FLAG, STATUS_CODE, WBS_SHORT_NAME, WBS_NAME, GUID) "
            "VALUES (1, 1, NULL, 1, 1, 1.0, 'Y', 'N', 'WS_Open', 'EPS', 'EPS', 'abcdefghijklmnopqrstuv')"
        )
        conn.commit()
    finally:
        conn.close()
