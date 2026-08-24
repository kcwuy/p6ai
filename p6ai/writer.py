# -*- coding: utf-8 -*-
"""
P6 Professional 独立版 SQLite 数据库直写引擎。
"""

import base64
import datetime
import os
import shutil
import sqlite3
import uuid

from .plan import compute_estimates, validate_plan_data
from .schema import check_database


DEFAULT_DB = r"C:\Users\Kong\Documents\PPMDBSQLite.db"


def now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_guid() -> str:
    """P6 独立版 GUID 为 22 位 base64（16 字节 UUID 去掉填充）。"""
    return base64.b64encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")


def insert(cur, table: str, data: dict):
    cols = ", ".join(data.keys())
    marks = ", ".join("?" * len(data))
    cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))


def get_max(cur, table: str, col: str) -> int:
    cur.execute(f"SELECT COALESCE(MAX({col}), 0) FROM {table}")
    return int(cur.fetchone()[0])


def resolve_calendar(cur, plan_data):
    """按名称精确匹配 -> 关键词模糊匹配 -> 默认日历 -> 首个日历。"""
    target = plan_data.get("calendar_name")
    if target:
        cur.execute(
            "SELECT CLNDR_ID, CLNDR_NAME, DAY_HR_CNT FROM CALENDAR WHERE CLNDR_NAME = ? LIMIT 1",
            (target,),
        )
        row = cur.fetchone()
        if row:
            return row
    keywords = ["Standard", "5 Day", "工作日", "标准"]
    cond = " OR ".join(["CLNDR_NAME LIKE ?" for _ in keywords])
    params = [f"%{kw}%" for kw in keywords]
    cur.execute(f"SELECT CLNDR_ID, CLNDR_NAME, DAY_HR_CNT FROM CALENDAR WHERE {cond} LIMIT 1", params)
    row = cur.fetchone()
    if row:
        return row
    cur.execute("SELECT CLNDR_ID, CLNDR_NAME, DAY_HR_CNT FROM CALENDAR WHERE DEFAULT_FLAG = 'Y' LIMIT 1")
    row = cur.fetchone()
    if row:
        return row
    cur.execute("SELECT CLNDR_ID, CLNDR_NAME, DAY_HR_CNT FROM CALENDAR LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise RuntimeError("CALENDAR 表为空，P6 数据库不完整")
    return row


def resolve_obs(cur) -> int:
    cur.execute("SELECT OBS_ID FROM OBS WHERE PARENT_OBS_ID IS NULL ORDER BY OBS_ID LIMIT 1")
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute("SELECT MIN(OBS_ID) FROM OBS")
    row = cur.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    raise RuntimeError("OBS 表完全为空，无法满足组织分解外键约束")


def resolve_eps_root(cur):
    """EPS 根节点：PROJ_NODE_FLAG='Y' 且 PARENT_WBS_ID IS NULL 的顶层节点。"""
    cur.execute(
        "SELECT WBS_ID FROM PROJWBS WHERE PROJ_NODE_FLAG = 'Y' AND PARENT_WBS_ID IS NULL "
        "AND STATUS_CODE = 'WS_Open' ORDER BY WBS_ID LIMIT 1"
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def sync_nextkey(cur, key_name: str, next_val: int):
    """P6 的 NEXTKEY 只增不减，避免与历史已分配序列冲突。"""
    cur.execute("SELECT KEY_SEQ_NUM FROM NEXTKEY WHERE KEY_NAME = ?", (key_name,))
    row = cur.fetchone()
    cur_next = int(row[0]) if row else 0
    target = max(cur_next, next_val)
    now = now_str()
    if row:
        cur.execute(
            "UPDATE NEXTKEY SET KEY_SEQ_NUM = ?, UPDATE_DATE = ?, UPDATE_USER = 'NotPrmUser' WHERE KEY_NAME = ?",
            (target, now, key_name),
        )
    else:
        cur.execute(
            "INSERT INTO NEXTKEY (KEY_NAME, KEY_SEQ_NUM, CREATE_DATE, CREATE_USER, UPDATE_DATE, UPDATE_USER) "
            "VALUES (?, ?, ?, 'NotPrmUser', ?, 'NotPrmUser')",
            (key_name, target, now, now),
        )
    return target


def create_p6_project(db_path: str, plan_data: dict, backup: bool = True) -> dict:
    """校验计划数据并把项目直接写入 P6 独立版 SQLite 数据库。"""
    valid, msg, topo_order = validate_plan_data(plan_data)
    if not valid:
        return {"status": "error", "message": f"数据校验失败: {msg}", "project_id": None}

    if not os.path.exists(db_path):
        return {"status": "error", "message": f"未找到指定的 P6 数据库文件: {db_path}", "project_id": None}

    # 写入前结构自检，防止误写入 EPPM 库或其它版本
    check = check_database(db_path, probe_lock=False)
    if not check["compatible"]:
        return {"status": "error", "message": f"结构自检未通过: {check['message']}", "project_id": None}

    # 获取写锁；拿不到说明 P6 或其他程序正占用数据库
    try:
        conn = sqlite3.connect(db_path, timeout=3)
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        return {
            "status": "error",
            "message": "数据库被占用（P6 Professional 可能正在运行），请先完全关闭 P6 再重试",
            "project_id": None,
        }

    backup_path = None
    if backup:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.bak_{timestamp}"
        try:
            shutil.copyfile(db_path, backup_path)
        except Exception as e:
            conn.rollback()
            conn.close()
            return {"status": "error", "message": f"自动备份失败: {e}", "project_id": None}

    cur = conn.cursor()
    try:
        clndr = resolve_calendar(cur, plan_data)
        clndr_id = int(clndr[0])
        day_hr = float(clndr[2] or 8.0)
        obs_id = resolve_obs(cur)
        eps_wbs_id = resolve_eps_root(cur)
        now = now_str()

        proj_id = get_max(cur, "PROJECT", "PROJ_ID") + 1
        root_wbs_id = get_max(cur, "PROJWBS", "WBS_ID") + 1
        cur_wbs_id = root_wbs_id

        est, task_hours, proj_start_dt = compute_estimates(plan_data, topo_order, day_hr)
        plan_end_dt = max((end for _, end in est.values()), default=proj_start_dt)

        # ---- PROJECT ----
        project_row = {
            "PROJ_ID": proj_id,
            "FY_START_MONTH_NUM": 1,
            "RSRC_SELF_ADD_FLAG": "Y",
            "ALLOW_COMPLETE_FLAG": "Y",
            "RSRC_MULTI_ASSIGN_FLAG": "Y",
            "CHECKOUT_FLAG": "N",
            "PROJECT_FLAG": "Y",
            "STEP_COMPLETE_FLAG": "N",
            "COST_QTY_RECALC_FLAG": "N",
            "BATCH_SUM_FLAG": "Y",
            "NAME_SEP_CHAR": ".",
            "DEF_COMPLETE_PCT_TYPE": "CP_Drtn",
            "PROJ_SHORT_NAME": plan_data["project_code"],
            # 独立版 P6 普通项目的 ORIG_PROJ_ID 必须为空；
            # 填入非空值会让 P6 把项目当作基线副本，从项目列表中隐藏
            "ORIG_PROJ_ID": None,
            "CLNDR_ID": clndr_id,
            "TASK_CODE_BASE": 1000,
            "TASK_CODE_STEP": 10,
            "PRIORITY_NUM": 10,
            "WBS_MAX_SUM_LEVEL": 2,
            "STRGY_PRIORITY_NUM": 500,
            "CRITICAL_DRTN_HR_CNT": 0.0,
            "DEF_COST_PER_QTY": 0.0,
            "LAST_RECALC_DATE": now[:10] + " 00:00:00",
            "PLAN_START_DATE": plan_data["start_date"],
            "PLAN_END_DATE": plan_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "ADD_DATE": now,
            "DEF_DURATION_TYPE": "DT_FixedDUR2",
            "TASK_CODE_PREFIX": "A",
            "GUID": new_guid(),
            "DEF_QTY_TYPE": "QT_Hour",
            "ADD_BY_NAME": "ADMIN",
            "DEF_RATE_TYPE": "COST_PER_QTY",
            "ADD_ACT_REMAIN_FLAG": "N",
            "ACT_THIS_PER_LINK_FLAG": "Y",
            "DEF_TASK_TYPE": "TT_Task",
            "ACT_PCT_LINK_FLAG": "Y",
            "CRITICAL_PATH_TYPE": "CT_TotFloat",
            "TASK_CODE_PREFIX_FLAG": "Y",
            "DEF_ROLLUP_DATES_FLAG": "Y",
            "USE_PROJECT_BASELINE_FLAG": "Y",
            "REM_TARGET_LINK_FLAG": "Y",
            "RESET_PLANNED_FLAG": "N",
            "ALLOW_NEG_ACT_FLAG": "N",
            "SUM_ASSIGN_LEVEL": "SL_Taskrsrc",
            "FINTMPL_ID": 1,
            "CONTROL_UPDATES_FLAG": "N",
            "HIST_INTERVAL": "Month",
            "HIST_LEVEL": "HL_None",
            "CREATE_DATE": now,
            "CREATE_USER": "NotPrmUser",
            "UPDATE_DATE": now,
            "UPDATE_USER": "NotPrmUser",
        }
        insert(cur, "PROJECT", project_row)

        # ---- 根 WBS（项目节点，挂接 EPS）----
        root_wbs_row = {
            "WBS_ID": root_wbs_id,
            "PROJ_ID": proj_id,
            "PARENT_WBS_ID": eps_wbs_id,
            "OBS_ID": obs_id,
            "SEQ_NUM": 1,
            "EST_WT": 1.0,
            "PROJ_NODE_FLAG": "Y",
            "SUM_DATA_FLAG": "N",
            "STATUS_CODE": "WS_Open",
            "WBS_SHORT_NAME": plan_data["project_code"],
            "WBS_NAME": plan_data["project_name"],
            "EV_USER_PCT": 6,
            "EV_ETC_USER_VALUE": 0.88,
            "EV_COMPUTE_TYPE": "EC_Cmp_pct",
            "EV_ETC_COMPUTE_TYPE": "EE_Rem_hr",
            "GUID": new_guid(),
            "CREATE_DATE": now,
            "CREATE_USER": "NotPrmUser",
            "UPDATE_DATE": now,
            "UPDATE_USER": "NotPrmUser",
        }
        insert(cur, "PROJWBS", root_wbs_row)

        # ---- 子 WBS（动态收敛，支持任意层级）----
        wbs_id_map = {None: root_wbs_id}
        pending = plan_data.get("wbs_tree", [])[:]
        while pending:
            remaining = []
            progress = False
            for idx, wbs in enumerate(pending):
                parent_code = wbs.get("parent")
                if parent_code in wbs_id_map:
                    cur_wbs_id += 1
                    wbs_row = {
                        "WBS_ID": cur_wbs_id,
                        "PROJ_ID": proj_id,
                        "PARENT_WBS_ID": wbs_id_map[parent_code],
                        "OBS_ID": obs_id,
                        "SEQ_NUM": (idx + 1) * 10,
                        "EST_WT": 1.0,
                        "PROJ_NODE_FLAG": "N",
                        "SUM_DATA_FLAG": "N",
                        "STATUS_CODE": "WS_Open",
                        "WBS_SHORT_NAME": wbs["wbs_code"],
                        "WBS_NAME": wbs["wbs_name"],
                        "EV_USER_PCT": 6,
                        "EV_ETC_USER_VALUE": 0.88,
                        "EV_COMPUTE_TYPE": "EC_Cmp_pct",
                        "EV_ETC_COMPUTE_TYPE": "EE_Rem_hr",
                        "GUID": new_guid(),
                        "CREATE_DATE": now,
                        "CREATE_USER": "NotPrmUser",
                        "UPDATE_DATE": now,
                        "UPDATE_USER": "NotPrmUser",
                    }
                    insert(cur, "PROJWBS", wbs_row)
                    wbs_id_map[wbs["wbs_code"]] = cur_wbs_id
                    progress = True
                else:
                    remaining.append(wbs)
            pending = remaining
            if not progress:
                raise RuntimeError(
                    "WBS 父节点引用无法解析（校验阶段应已拦截）: "
                    + ", ".join(w["wbs_code"] for w in pending)
                )

        # ---- TASK ----
        cur_task_id = get_max(cur, "TASK", "TASK_ID")
        task_code_to_id = {}
        for task in plan_data.get("tasks", []):
            cur_task_id += 1
            task_code = task["task_code"]
            task_start, task_end = est[task_code]
            duration_h = task_hours[task_code]
            task_row = {
                "TASK_ID": cur_task_id,
                "PROJ_ID": proj_id,
                "WBS_ID": wbs_id_map.get(task["wbs_code"], root_wbs_id),
                "CLNDR_ID": clndr_id,
                "PHYS_COMPLETE_PCT": 0.0,
                "REV_FDBK_FLAG": "N",
                "EST_WT": 1.0,
                "LOCK_PLAN_FLAG": "N",
                "AUTO_COMPUTE_ACT_FLAG": "Y",
                "COMPLETE_PCT_TYPE": "CP_Units",
                "TASK_TYPE": "TT_Task",
                "DURATION_TYPE": "DT_FixedDrtn",
                "STATUS_CODE": "TK_NotStart",
                "TASK_CODE": task_code,
                "TASK_NAME": task["task_name"],
                "TOTAL_FLOAT_HR_CNT": 0.0,
                "FREE_FLOAT_HR_CNT": 0.0,
                "REMAIN_DRTN_HR_CNT": duration_h,
                "ACT_WORK_QTY": 0.0,
                "REMAIN_WORK_QTY": 0.0,
                "TARGET_WORK_QTY": 0.0,
                "TARGET_DRTN_HR_CNT": duration_h,
                "TARGET_EQUIP_QTY": 0.0,
                "ACT_EQUIP_QTY": 0.0,
                "REMAIN_EQUIP_QTY": 0.0,
                "TARGET_START_DATE": task_start.strftime("%Y-%m-%d %H:%M:%S"),
                "TARGET_END_DATE": task_end.strftime("%Y-%m-%d %H:%M:%S"),
                "PRIORITY_TYPE": "PT_Normal",
                "GUID": new_guid(),
                "DRIVING_PATH_FLAG": "Y",
                "CREATE_DATE": now,
                "CREATE_USER": "NotPrmUser",
                "UPDATE_DATE": now,
                "UPDATE_USER": "NotPrmUser",
                "CONTROL_UPDATES_FLAG": "N",
            }
            insert(cur, "TASK", task_row)
            task_code_to_id[task_code] = cur_task_id

        # ---- TASKPRED ----
        cur_pred_id = get_max(cur, "TASKPRED", "TASK_PRED_ID")
        for rel in plan_data.get("relationships", []):
            cur_pred_id += 1
            pred_row = {
                "TASK_PRED_ID": cur_pred_id,
                "TASK_ID": task_code_to_id[rel["succ_code"]],
                "PRED_TASK_ID": task_code_to_id[rel["pred_code"]],
                "PROJ_ID": proj_id,
                "PRED_PROJ_ID": proj_id,
                "PRED_TYPE": rel.get("type", "PR_FS"),
                "LAG_HR_CNT": float(rel.get("lag_days", 0)) * day_hr,
                "CREATE_DATE": now,
                "CREATE_USER": "NotPrmUser",
                "UPDATE_DATE": now,
                "UPDATE_USER": "NotPrmUser",
            }
            insert(cur, "TASKPRED", pred_row)

        # ---- NEXTKEY 对齐 ----
        sync_nextkey(cur, "project_proj_id", proj_id + 1)
        sync_nextkey(cur, "projwbs_wbs_id", cur_wbs_id + 1)
        sync_nextkey(cur, "task_task_id", cur_task_id + 1)
        sync_nextkey(cur, "taskpred_task_pred_id", cur_pred_id + 1)

        # ---- 事务内回读校验 ----
        n_tasks = cur.execute("SELECT COUNT(*) FROM TASK WHERE PROJ_ID = ?", (proj_id,)).fetchone()[0]
        n_wbs = cur.execute("SELECT COUNT(*) FROM PROJWBS WHERE PROJ_ID = ?", (proj_id,)).fetchone()[0]
        n_preds = cur.execute("SELECT COUNT(*) FROM TASKPRED WHERE PROJ_ID = ?", (proj_id,)).fetchone()[0]

        conn.commit()
        try:
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except sqlite3.OperationalError:
            pass

        return {
            "status": "success",
            "message": "项目创建成功，序列与外键已对齐",
            "project_id": proj_id,
            "project_code": plan_data["project_code"],
            "project_name": plan_data["project_name"],
            "root_wbs_id": root_wbs_id,
            "calendar_name": clndr[1],
            "counts": {"wbs": n_wbs, "tasks": n_tasks, "relationships": n_preds},
            "backup_path": backup_path,
        }

    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": f"写入失败，事务已整体回滚: {e}", "project_id": None}
    finally:
        conn.close()
