# -*- coding: utf-8 -*-
"""
P6 数据库结构自检与版本识别。

工具只面向 Primavera P6 Professional 独立版（SQLite PMDB）。
自检模块在写入前确认：
  - 目标文件确实是 SQLite 数据库
  - 关键表与字段与当前版本兼容
  - 没有混入 EPPM（网络版）结构的字段
  - 数据库未被其他程序（如 P6 客户端）占用
"""

import os
import sqlite3


# 写入引擎依赖的关键表与必需字段（依据 P6 Professional 23.12 独立版实测）
REQUIRED_TABLES = {
    "PROJECT": [
        "PROJ_ID", "FY_START_MONTH_NUM", "RSRC_SELF_ADD_FLAG", "ALLOW_COMPLETE_FLAG",
        "RSRC_MULTI_ASSIGN_FLAG", "CHECKOUT_FLAG", "PROJECT_FLAG", "STEP_COMPLETE_FLAG",
        "COST_QTY_RECALC_FLAG", "BATCH_SUM_FLAG", "NAME_SEP_CHAR", "DEF_COMPLETE_PCT_TYPE",
        "PROJ_SHORT_NAME", "ORIG_PROJ_ID", "CLNDR_ID", "TASK_CODE_BASE", "TASK_CODE_STEP",
        "PRIORITY_NUM", "WBS_MAX_SUM_LEVEL", "STRGY_PRIORITY_NUM", "CRITICAL_DRTN_HR_CNT",
        "DEF_COST_PER_QTY", "LAST_RECALC_DATE", "PLAN_START_DATE", "PLAN_END_DATE",
        "ADD_DATE", "DEF_DURATION_TYPE", "TASK_CODE_PREFIX", "GUID", "DEF_QTY_TYPE",
        "ADD_BY_NAME", "DEF_RATE_TYPE", "ADD_ACT_REMAIN_FLAG", "ACT_THIS_PER_LINK_FLAG",
        "DEF_TASK_TYPE", "ACT_PCT_LINK_FLAG", "CRITICAL_PATH_TYPE", "TASK_CODE_PREFIX_FLAG",
        "DEF_ROLLUP_DATES_FLAG", "USE_PROJECT_BASELINE_FLAG", "REM_TARGET_LINK_FLAG",
        "RESET_PLANNED_FLAG", "ALLOW_NEG_ACT_FLAG", "SUM_ASSIGN_LEVEL", "FINTMPL_ID",
        "CONTROL_UPDATES_FLAG", "HIST_INTERVAL", "HIST_LEVEL",
        "CREATE_DATE", "CREATE_USER", "UPDATE_DATE", "UPDATE_USER",
    ],
    "PROJWBS": [
        "WBS_ID", "PROJ_ID", "PARENT_WBS_ID", "WBS_SHORT_NAME", "WBS_NAME",
        "PROJ_NODE_FLAG", "SEQ_NUM", "STATUS_CODE", "OBS_ID", "GUID",
        "EST_WT", "SUM_DATA_FLAG",
        "EV_USER_PCT", "EV_ETC_USER_VALUE", "EV_COMPUTE_TYPE", "EV_ETC_COMPUTE_TYPE",
        "CREATE_DATE", "CREATE_USER", "UPDATE_DATE", "UPDATE_USER",
    ],
    "TASK": [
        "TASK_ID", "PROJ_ID", "WBS_ID", "CLNDR_ID",
        "PHYS_COMPLETE_PCT", "REV_FDBK_FLAG", "EST_WT", "LOCK_PLAN_FLAG",
        "AUTO_COMPUTE_ACT_FLAG", "COMPLETE_PCT_TYPE", "TASK_TYPE", "DURATION_TYPE",
        "STATUS_CODE", "TASK_CODE", "TASK_NAME",
        "TOTAL_FLOAT_HR_CNT", "FREE_FLOAT_HR_CNT", "REMAIN_DRTN_HR_CNT",
        "ACT_WORK_QTY", "REMAIN_WORK_QTY", "TARGET_WORK_QTY", "TARGET_DRTN_HR_CNT",
        "TARGET_EQUIP_QTY", "ACT_EQUIP_QTY", "REMAIN_EQUIP_QTY",
        "TARGET_START_DATE", "TARGET_END_DATE", "PRIORITY_TYPE", "GUID",
        "DRIVING_PATH_FLAG", "CONTROL_UPDATES_FLAG",
        "CREATE_DATE", "CREATE_USER", "UPDATE_DATE", "UPDATE_USER",
    ],
    "TASKPRED": [
        "TASK_PRED_ID", "TASK_ID", "PRED_TASK_ID", "PROJ_ID", "PRED_PROJ_ID",
        "PRED_TYPE", "LAG_HR_CNT",
        "CREATE_DATE", "CREATE_USER", "UPDATE_DATE", "UPDATE_USER",
    ],
    "CALENDAR": ["CLNDR_ID", "CLNDR_NAME", "CLNDR_TYPE", "DAY_HR_CNT", "DEFAULT_FLAG"],
    "OBS": ["OBS_ID", "PARENT_OBS_ID", "OBS_NAME"],
    "NEXTKEY": ["KEY_NAME", "KEY_SEQ_NUM", "CREATE_DATE", "CREATE_USER", "UPDATE_DATE", "UPDATE_USER"],
}


# EPPM（网络版）特征字段；若存在说明不是独立版 SQLite，工具不应继续写入。
# 注意：PROJ_URL 在 23.12 独立版中同样存在，不能作为判别依据。
EPPM_MARKERS = {
    "PROJECT": ["STATUS_CODE", "WBS_ID"],
}


SQLITE_MAGIC = b"SQLite format 3\x00"


def is_sqlite_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def detect_wal_mode(path: str) -> bool:
    """SQLite 文件头第 18/19 字节为 2 表示 WAL 日志模式。"""
    try:
        with open(path, "rb") as f:
            f.seek(18)
            header = f.read(2)
        return header == b"\x02\x02"
    except OSError:
        return False


def detect_database_version(db_path: str):
    """从 PREFER 表读取数据库版本标识，如 'PPMDB,2312.0000.0000.0005'。"""
    try:
        conn = sqlite3.connect(f"file:{db_path.replace(os.sep, '/')}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return None, None
    try:
        cur = conn.cursor()
        cur.execute("SELECT DATABASE_VERSION, MIN_PRO_VERSION FROM PREFER LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None, None
        db_version, min_pro_version = row
        friendly = None
        if db_version and "," in str(db_version):
            code = str(db_version).split(",", 1)[1].split(".")[0]
            if len(code) == 4:
                friendly = f"{code[:2]}.{code[2:]}"
        return db_version, min_pro_version, friendly
    except sqlite3.Error:
        return None, None
    finally:
        conn.close()


def check_database(db_path: str, probe_lock: bool = True) -> dict:
    """对 P6 数据库执行结构自检，返回机器可读的报告。"""
    report = {
        "path": db_path,
        "exists": False,
        "is_sqlite": False,
        "wal_mode": None,
        "database_version": None,
        "min_pro_version": None,
        "friendly_version": None,
        "missing_tables": [],
        "missing_columns": {},
        "epmm_markers": {},
        "locked": None,
        "compatible": False,
        "status": "error",
        "message": "",
    }

    if not os.path.exists(db_path):
        report["message"] = f"数据库文件不存在: {db_path}"
        return report
    report["exists"] = True

    if not is_sqlite_file(db_path):
        report["message"] = "文件不是有效的 SQLite 数据库（文件头不匹配）"
        return report
    report["is_sqlite"] = True
    report["wal_mode"] = detect_wal_mode(db_path)

    db_version, min_pro_version, friendly = detect_database_version(db_path)
    report["database_version"] = db_version
    report["min_pro_version"] = min_pro_version
    report["friendly_version"] = friendly

    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {r[0].upper() for r in cur.fetchall()}

        missing_tables = [t for t in REQUIRED_TABLES if t not in existing_tables]
        report["missing_tables"] = missing_tables

        for table, required_cols in REQUIRED_TABLES.items():
            if table not in existing_tables:
                continue
            cur.execute(f"PRAGMA table_info({table})")
            actual = {r[1].upper() for r in cur.fetchall()}
            missing = [c for c in required_cols if c not in actual]
            if missing:
                report["missing_columns"][table] = missing

        for table, marker_cols in EPPM_MARKERS.items():
            if table not in existing_tables:
                continue
            cur.execute(f"PRAGMA table_info({table})")
            actual = {r[1].upper() for r in cur.fetchall()}
            found = [c for c in marker_cols if c in actual]
            if found:
                report["epmm_markers"][table] = found

        if probe_lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.rollback()
                report["locked"] = False
            except sqlite3.OperationalError:
                report["locked"] = True

        if report["locked"]:
            report["status"] = "locked"
            report["message"] = "数据库被占用（P6 Professional 可能正在运行），请先完全关闭 P6"
            return report

        if missing_tables or report["missing_columns"]:
            report["status"] = "incompatible"
            report["message"] = "数据库结构与当前版本不兼容，禁止写入"
            return report

        if report["epmm_markers"]:
            report["status"] = "incompatible"
            report["message"] = "检测到 EPPM（网络版）结构特征，此工具仅支持 P6 Professional 独立版 SQLite"
            return report

        report["status"] = "ok"
        report["message"] = "结构与支持的 P6 独立版 SQLite 一致"
        report["compatible"] = True
        return report
    except sqlite3.Error as e:
        report["status"] = "error"
        report["message"] = f"读取数据库失败: {e}"
        return report
    finally:
        if conn is not None:
            conn.close()


def format_report(report: dict) -> str:
    """将自检报告格式化为人类可读文本。"""
    lines = []
    lines.append("=" * 60)
    lines.append("P6 数据库结构自检报告")
    lines.append("=" * 60)
    lines.append(f"数据库路径 : {report['path']}")
    lines.append(f"文件存在   : {'是' if report['exists'] else '否'}")
    if not report["exists"]:
        return "\n".join(lines) + "\n\n" + report["message"]
    lines.append(f"SQLite 格式 : {'是' if report['is_sqlite'] else '否'}")
    lines.append(f"WAL 模式   : {'是' if report['wal_mode'] else '否'}")
    lines.append(f"数据库版本 : {report['database_version'] or '未知'}")
    lines.append(f"最低 P6 版本: {report['min_pro_version'] or '未知'}")
    if report["friendly_version"]:
        lines.append(f"识别为 P6   : {report['friendly_version']} 独立版")
    if report["missing_tables"]:
        lines.append(f"缺少表     : {', '.join(report['missing_tables'])}")
    for table, cols in report["missing_columns"].items():
        lines.append(f"缺少字段   : {table}.{', '.join(cols)}")
    for table, cols in report["epmm_markers"].items():
        lines.append(f"EPPM 特征   : {table}.{', '.join(cols)}（网络版结构，非独立版）")
    if report["locked"] is not None:
        lines.append(f"数据库占用 : {'是（P6 正在运行？）' if report['locked'] else '否'}")
    status_cn = {"ok": "兼容", "incompatible": "不兼容", "locked": "被占用", "error": "异常"}
    lines.append("-" * 60)
    lines.append(f"结论       : {status_cn.get(report['status'], report['status'])}")
    lines.append(report["message"])
    return "\n".join(lines)
