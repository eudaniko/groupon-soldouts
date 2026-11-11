"""The config-only rollout for Friday's gate: suppressed_deal_ids via env_overrides.json, routing code untouched."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "routing"))
import routing.plan as plan  # noqa: E402

PROPOSED = json.loads((ROOT / "proposal" / "env_overrides.json").read_text())
CURRENT = json.loads((ROOT / "routing" / "config" / "env_overrides.json").read_text())
ROWS = plan.load_rows(ROOT / "routing" / "input" / "todays_soldouts.csv")


def run(overrides):
    orig = plan.load_overrides
    plan.load_overrides = lambda: overrides
    try:
        return plan.build_plan(ROWS, config=plan.load_config(), priors=plan.load_priors(), suppressions=(set(), set()))
    finally:
        plan.load_overrides = orig


class ConfigOnlyTest(unittest.TestCase):
    def test_keeps_the_three_ops_suppressions(self):
        # env_overrides REPLACES the list from routing.json, so the existing ids must be carried over.
        base = json.loads((ROOT / "routing" / "config" / "routing.json").read_text())["suppressed_deal_ids"]
        self.assertTrue(set(base) <= set(PROPOSED["routing"]["suppressed_deal_ids"]))

    def test_priors_override_unchanged(self):
        self.assertEqual(PROPOSED["priors"], CURRENT["priors"])

    def test_listed_auto_replenish_deals_get_no_task(self):
        today, carried = run(PROPOSED)
        ids = {p["task_id"] for p in today + carried}
        self.assertFalse({"T-0027", "T-0028", "T-0036"} & ids)

    def test_off_means_identical_to_today(self):
        off = {k: v for k, v in PROPOSED.items() if k != "routing"}
        self.assertEqual(run(off), run(CURRENT))

    def test_list_is_automation_only(self):
        import csv
        rows = list(csv.DictReader(open(ROOT / "proposal" / "suppressions.csv")))
        self.assertTrue(rows)
        self.assertTrue(all(r["source"] == "auto_replenish_schedules" for r in rows))


if __name__ == "__main__":
    unittest.main()
