# -*- coding: utf-8 -*-

import copy
import unittest

from p6ai.plan import DEMO_PLAN, compute_estimates, validate_plan_data


class TestValidatePlan(unittest.TestCase):
    def test_demo_plan_passes(self):
        ok, msg, order = validate_plan_data(DEMO_PLAN)
        self.assertTrue(ok, msg)
        self.assertEqual(len(order), 4)

    def test_missing_top_field(self):
        plan = copy.deepcopy(DEMO_PLAN)
        del plan["tasks"]
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)
        self.assertIn("tasks", msg)

    def test_duplicate_task_code(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["tasks"][1] = dict(plan["tasks"][0])
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)
        self.assertIn("重复", msg)

    def test_bad_wbs_reference(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["tasks"][0]["wbs_code"] = "WBS.NOPE"
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)
        self.assertIn("WBS.NOPE", msg)

    def test_non_positive_duration(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["tasks"][0]["duration_days"] = 0
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)

    def test_cycle_detected(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["relationships"].append(
            {"pred_code": "A1040", "succ_code": "A1010", "type": "PR_FS", "lag_days": 0}
        )
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)
        self.assertIn("循环", msg)

    def test_bad_relationship_type(self):
        plan = copy.deepcopy(DEMO_PLAN)
        plan["relationships"][0]["type"] = "PR_XX"
        ok, msg, _ = validate_plan_data(plan)
        self.assertFalse(ok)


class TestComputeEstimates(unittest.TestCase):
    def test_fs_chain_timing(self):
        ok, msg, order = validate_plan_data(DEMO_PLAN)
        self.assertTrue(ok)
        est, hours, start = compute_estimates(DEMO_PLAN, order, 8.0)
        self.assertEqual(hours["A1010"], 32.0)
        # A1020 在 A1010 结束后开始（无 lag）
        self.assertEqual(est["A1020"][0], est["A1010"][1])
        # A1030 在 A1020 结束后 + 3 天（24 小时）开始
        self.assertEqual(
            est["A1030"][0] - est["A1020"][1],
            __import__("datetime").timedelta(hours=24),
        )


if __name__ == "__main__":
    unittest.main()
