import json
import tempfile
import unittest
from pathlib import Path

from routing.plan import build_plan, load_config, load_rows, load_suppression_sets, suppression_on
from routing.suppressions import load_suppressions

ROOT = Path(__file__).resolve().parent.parent
ROWS = load_rows(ROOT / "input" / "todays_soldouts.csv")
BY_TASK = {r["task_id"]: r for r in ROWS}
NONE = (set(), set())


def ids(plan):
    today, carried = plan
    return [p["task_id"] for p in today], [p["task_id"] for p in carried]


class SwitchOffTest(unittest.TestCase):
    def test_off_output_identical_to_no_suppression(self):
        config = load_config()
        self.assertFalse(suppression_on(config))
        self.assertEqual(build_plan(ROWS, config=config), build_plan(ROWS, config=config, suppressions=NONE))

    def test_off_ignores_a_full_suppression_file(self):
        config = dict(load_config(), suppress_soldout_tasks=False)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_text("deal_id,merchant_id,reason,source,added_on\n"
                         + "".join(f"{r['deal_id']},,x,test,2026-11-01\n" for r in ROWS))
            config["suppression_file"] = str(p)
            self.assertEqual(load_suppression_sets(config), NONE)

    def test_only_json_true_turns_it_on(self):
        for value in ("true", "false", 1, "1", None, False):
            self.assertFalse(suppression_on({"suppress_soldout_tasks": value}), value)
        self.assertTrue(suppression_on({"suppress_soldout_tasks": True}))


class SwitchOnTest(unittest.TestCase):
    def setUp(self):
        self.config = dict(load_config(), suppress_soldout_tasks=True)

    def plan(self, deals=(), merchants=()):
        return ids(build_plan(ROWS, config=self.config, suppressions=(set(deals), set(merchants))))

    def test_suppressed_deal_gets_no_task(self):
        today, carried = self.plan(deals={"D10001-2"})  # T-0005
        self.assertNotIn("T-0005", today + carried)

    def test_merchant_wide_row_removes_all_its_deals(self):
        today, carried = self.plan(merchants={"M11688"})  # T-0008, T-0033
        self.assertFalse({"T-0008", "T-0033"} & set(today + carried))

    def test_promised_callback_is_never_suppressed(self):
        today, _ = self.plan(deals={"D10002-1"}, merchants={"M11543"})  # T-0007, T-0004 promised
        self.assertIn("T-0007", today)
        self.assertIn("T-0004", today)
        # the non-promised task of the same merchant does go
        today2, carried2 = self.plan(merchants={"M11543"})
        self.assertNotIn("T-0022", today2 + carried2)

    def test_freed_slots_are_filled_from_carry_over(self):
        base_today, base_carried = self.plan()
        top_restock = next(t for t in base_today if BY_TASK[t]["callback_promised"] == "0")
        today, carried = self.plan(deals={BY_TASK[top_restock]["deal_id"]})
        self.assertEqual(len(today), len(base_today))
        self.assertEqual(len(carried), len(base_carried) - 1)

    def test_do_not_contact_still_dropped(self):
        today, carried = self.plan()
        self.assertNotIn("T-0006", today + carried)

    def test_reads_the_configured_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_text("deal_id,merchant_id,reason,source,added_on\n"
                         "D10127-2,M10127,auto-replenish weekly,auto_replenish_schedules,2026-11-11\n"
                         ",M10766,merchant asked: no restock calls,rep R10,2026-11-11\n")
            self.config["suppression_file"] = str(p)
            deals, merchants = load_suppression_sets(self.config)
            self.assertEqual(deals, {"D10127-2"})
            self.assertEqual(merchants, {"M10766"})
            today, carried = ids(build_plan(ROWS, config=self.config))
            self.assertFalse({"T-0034", "T-0009", "T-0017"} & set(today + carried))


class OverrideTest(unittest.TestCase):
    def test_env_override_wins_over_routing_json(self):
        import routing.plan as plan
        orig = plan.load_overrides
        try:
            plan.load_overrides = lambda: {"routing": {"suppress_soldout_tasks": True}}
            self.assertTrue(suppression_on(plan.load_config()))
            plan.load_overrides = lambda: {"routing": {"suppress_soldout_tasks": False}}
            self.assertFalse(suppression_on(plan.load_config()))
        finally:
            plan.load_overrides = orig

    def test_shipped_env_overrides_do_not_set_the_switch(self):
        overrides = json.loads((ROOT / "config" / "env_overrides.json").read_text())
        self.assertNotIn("suppress_soldout_tasks", overrides.get("routing", {}))


if __name__ == "__main__":
    unittest.main()
