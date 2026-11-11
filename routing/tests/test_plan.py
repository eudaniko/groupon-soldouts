import unittest
from pathlib import Path

from routing.plan import build_plan, load_config, load_priors, load_rows

ROWS = load_rows(Path(__file__).resolve().parent.parent / "input" / "todays_soldouts.csv")
BY_TASK = {r["task_id"]: r for r in ROWS}


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.today, self.carried = build_plan(ROWS)
        self.ids = [p["task_id"] for p in self.today]

    def test_do_not_contact_never_listed(self):
        for p in self.today + self.carried:
            self.assertEqual(BY_TASK[p["task_id"]]["do_not_contact"], "0")

    def test_budget(self):
        self.assertLessEqual(len(self.today) * self.config["minutes_per_task"], self.config["minutes_per_day"])

    def test_callbacks_come_first(self):
        promised = [i for i in self.ids if BY_TASK[i]["callback_promised"] == "1"]
        self.assertEqual(self.ids[: len(promised)], promised)

    def test_failed_attempts_pause(self):
        for p in self.today + self.carried:
            r = BY_TASK[p["task_id"]]
            if r["callback_promised"] == "0":
                self.assertLess(int(r["failed_attempts"]), self.config["max_failed_attempts"])

    def test_suppressed_deals_get_no_task(self):
        suppressed = set(self.config["suppressed_deal_ids"])
        for p in self.today + self.carried:
            self.assertNotIn(p["deal_id"], suppressed)

    def test_ranked_by_expected_gp(self):
        gps = [p["expected_gp"] for p in self.today if p["reason"] == "restock"]
        self.assertEqual(gps, sorted(gps, reverse=True))

    def test_restock_priors_present(self):
        priors = load_priors()
        self.assertGreater(priors["restock"]["called"], priors["restock"]["left_alone"])


if __name__ == "__main__":
    unittest.main()
