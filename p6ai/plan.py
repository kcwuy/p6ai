# -*- coding: utf-8 -*-
"""
计划数据模型与业务校验。

计划 JSON 采用以下结构：
{
  "project_code": "...",
  "project_name": "...",
  "start_date": "YYYY-MM-DD HH:MM:SS",
  "calendar_name": "...",
  "wbs_tree": [{"wbs_code", "wbs_name", "parent"}],
  "tasks": [{"task_code", "task_name", "wbs_code", "duration_days"}],
  "relationships": [{"pred_code", "succ_code", "type", "lag_days"}]
}
"""

import datetime
import json
from collections import deque


DEMO_PLAN = {
    "project_code": "PRJ-TEST-001",
    "project_name": "【测试】AI 直写验证项目",
    "start_date": "2026-09-01 08:00:00",
    "calendar_name": "Corporate - Standard Full Time",
    "wbs_tree": [
        {"wbs_code": "WBS.1", "wbs_name": "土建工程", "parent": None},
        {"wbs_code": "WBS.1.1", "wbs_name": "桩基与地基处理", "parent": "WBS.1"},
        {"wbs_code": "WBS.1.2", "wbs_name": "主体结构施工", "parent": "WBS.1"},
        {"wbs_code": "WBS.2", "wbs_name": "机电安装", "parent": None},
        {"wbs_code": "WBS.2.1", "wbs_name": "电气一次设备安装", "parent": "WBS.2"},
    ],
    "tasks": [
        {"task_code": "A1010", "task_name": "场地平整及放线", "wbs_code": "WBS.1.1", "duration_days": 4.0},
        {"task_code": "A1020", "task_name": "工程桩施工及检测", "wbs_code": "WBS.1.1", "duration_days": 15.5},
        {"task_code": "A1030", "task_name": "主体框架浇筑", "wbs_code": "WBS.1.2", "duration_days": 20.0},
        {"task_code": "A1040", "task_name": "主变压器就位及安装", "wbs_code": "WBS.2.1", "duration_days": 7.5},
    ],
    "relationships": [
        {"pred_code": "A1010", "succ_code": "A1020", "type": "PR_FS", "lag_days": 0},
        {"pred_code": "A1020", "succ_code": "A1030", "type": "PR_FS", "lag_days": 3},
        {"pred_code": "A1030", "succ_code": "A1040", "type": "PR_FS", "lag_days": 0},
    ],
}


def load_plan(path):
    """从 JSON 文件读取计划数据。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_plan_data(plan_data: dict):
    """校验计划数据的完整性与业务合法性。

    返回 (是否通过, 提示信息, 拓扑顺序列表)。
    """
    required_top = ["project_code", "project_name", "start_date", "wbs_tree", "tasks", "relationships"]
    for key in required_top:
        if key not in plan_data:
            return False, f"缺少必要顶级字段: {key}", []

    try:
        datetime.datetime.strptime(plan_data["start_date"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False, f"起始日期格式错误，必须为 'YYYY-MM-DD HH:MM:SS'：{plan_data['start_date']}", []

    wbs_codes = [w["wbs_code"] for w in plan_data.get("wbs_tree", [])]
    if len(set(wbs_codes)) != len(wbs_codes):
        return False, "WBS 树中存在重复的 wbs_code", []

    wbs_code_set = set(wbs_codes)
    for w in plan_data.get("wbs_tree", []):
        parent = w.get("parent")
        if parent is not None and parent not in wbs_code_set:
            return False, f"WBS [{w['wbs_code']}] 引用了不存在的父节点: {parent}", []

    tasks = plan_data.get("tasks", [])
    task_codes = [t["task_code"] for t in tasks]
    if len(set(task_codes)) != len(task_codes):
        return False, "任务列表中存在重复的 task_code", []

    for task in tasks:
        if task["wbs_code"] not in wbs_code_set:
            return False, f"任务 [{task['task_code']}] 引用了不存在的 WBS 代码: [{task['wbs_code']}]", []
        drtn = task.get("duration_days", 0)
        if not isinstance(drtn, (int, float)) or drtn <= 0:
            return False, f"任务 [{task['task_code']}] 的工期必须大于 0，当前为: {drtn}", []

    task_code_set = set(task_codes)
    relationships = plan_data.get("relationships", [])
    for rel in relationships:
        if rel["pred_code"] not in task_code_set:
            return False, f"逻辑关系错误：前驱任务 [{rel['pred_code']}] 不存在", []
        if rel["succ_code"] not in task_code_set:
            return False, f"逻辑关系错误：后继任务 [{rel['succ_code']}] 不存在", []
        if rel.get("type", "PR_FS") not in ["PR_FS", "PR_SS", "PR_FF", "PR_SF"]:
            return False, f"不支持的逻辑关系类型: {rel.get('type')}", []

    # 拓扑排序（Kahn 算法），检测循环依赖
    graph = {code: [] for code in task_codes}
    indeg = {code: 0 for code in task_codes}
    for rel in relationships:
        graph[rel["pred_code"]].append(rel["succ_code"])
        indeg[rel["succ_code"]] += 1
    q = deque([code for code in task_codes if indeg[code] == 0])
    order = []
    while q:
        node = q.popleft()
        order.append(node)
        for neighbor in graph[node]:
            indeg[neighbor] -= 1
            if indeg[neighbor] == 0:
                q.append(neighbor)
    if len(order) != len(task_codes):
        return False, "逻辑关系中存在循环闭环，无法构成合法的工序网络图", []

    return True, "校验通过", order


def compute_estimates(plan_data: dict, topo_order: list, day_hr: float):
    """日历无关的粗略前推估算；P6 内按 F9 进度计算后会按日历精确重算。"""
    start_dt = datetime.datetime.strptime(plan_data["start_date"], "%Y-%m-%d %H:%M:%S")
    task_hours = {t["task_code"]: float(t["duration_days"]) * day_hr for t in plan_data["tasks"]}
    rels_by_succ = {}
    for rel in plan_data.get("relationships", []):
        rels_by_succ.setdefault(rel["succ_code"], []).append(rel)

    est = {}
    for code in topo_order:
        duration_h = task_hours[code]
        best_start = start_dt
        for rel in rels_by_succ.get(code, []):
            pred_start, pred_end = est[rel["pred_code"]]
            lag_h = float(rel.get("lag_days", 0)) * day_hr
            rtype = rel.get("type", "PR_FS")
            if rtype == "PR_SS":
                cand = pred_start + datetime.timedelta(hours=lag_h)
            elif rtype == "PR_FF":
                cand = pred_end + datetime.timedelta(hours=lag_h - duration_h)
            elif rtype == "PR_SF":
                cand = pred_start + datetime.timedelta(hours=lag_h - duration_h)
            else:  # PR_FS
                cand = pred_end + datetime.timedelta(hours=lag_h)
            if cand > best_start:
                best_start = cand
        est[code] = (best_start, best_start + datetime.timedelta(hours=duration_h))
    return est, task_hours, start_dt
