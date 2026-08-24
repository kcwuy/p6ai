# -*- coding: utf-8 -*-
"""
P6AI —— 面向 Primavera P6 Professional（独立版 SQLite）的 AI 计划建库工具。
"""

__version__ = "0.2.0"

from .plan import DEMO_PLAN, compute_estimates, validate_plan_data
from .schema import check_database
from .writer import DEFAULT_DB, create_p6_project

__all__ = [
    "__version__",
    "DEMO_PLAN",
    "DEFAULT_DB",
    "check_database",
    "compute_estimates",
    "create_p6_project",
    "validate_plan_data",
]
