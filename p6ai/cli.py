# -*- coding: utf-8 -*-
"""命令行入口：p6ai check / validate / create。"""

import argparse
import json
import sys

from .plan import DEMO_PLAN, load_plan, validate_plan_data
from .schema import check_database, format_report
from .writer import DEFAULT_DB, create_p6_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p6ai",
        description="AI 驱动的 Primavera P6 Professional（独立版 SQLite）计划建库工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="对 P6 数据库执行结构自检")
    p_check.add_argument("--db", "-d", default=DEFAULT_DB, help="P6 数据库文件路径")
    p_check.add_argument("--no-lock-probe", action="store_true", help="跳过数据库占用检测")

    p_validate = sub.add_parser("validate", help="校验计划 JSON（不写库）")
    p_validate.add_argument("--plan", "-p", default=None, help="计划 JSON 文件路径；缺省用内置演示计划")

    p_create = sub.add_parser("create", help="校验计划并写入 P6 数据库")
    p_create.add_argument("--plan", "-p", default=None, help="计划 JSON 文件路径；缺省用内置演示计划")
    p_create.add_argument("--db", "-d", default=DEFAULT_DB, help="P6 数据库文件路径")
    p_create.add_argument("--no-backup", action="store_true", help="写入前不自动备份（不推荐）")

    return parser


def cmd_check(args) -> int:
    report = check_database(args.db, probe_lock=not args.no_lock_probe)
    print(format_report(report))
    return 0 if report["status"] in ("ok",) else 1


def cmd_validate(args) -> int:
    plan = load_plan(args.plan) if args.plan else DEMO_PLAN
    ok, msg, order = validate_plan_data(plan)
    print(f"校验结果: {'通过' if ok else '失败'} —— {msg}")
    if ok:
        print(f"拓扑顺序: {' -> '.join(order)}")
        return 0
    return 1


def cmd_create(args) -> int:
    plan = load_plan(args.plan) if args.plan else DEMO_PLAN
    result = create_p6_project(args.db, plan, backup=not args.no_backup)
    print("执行结果:", json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "create":
        return cmd_create(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
