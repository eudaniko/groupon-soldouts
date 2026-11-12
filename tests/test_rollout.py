import unittest

from soldouts.holdout import in_holdout
from soldouts import measure
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bs", Path(__file__).resolve().parent.parent / "scripts" / "build_suppressions.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def ctx():
    s = lambda sid, mid, end="": {"schedule_id": sid, "merchant_id": mid, "start_date": "2026-01-01", "end_date": end,
                                  "cadence": "weekly", "top_up_qty": "5", "created_by": "merchant_ops"}
    merchants = {f"M{i}": {"band": b, "do_not_contact": dnc} for i, b, dnc in
                 [(1, "B", False), (2, "A", False), (3, "C", True), (4, "D", False), (5, "C", False)]}
    return {"merchants": merchants, "schedules": {
        "D1-1": [s("AR1", "M1")], "D2-1": [s("AR2", "M2")], "D3-1": [s("AR3", "M3")],
        "D4-1": [s("AR4", "M4", end="2026-12-01")], "D5-1": [s("AR5", "M5", end="2027-03-01")]}}


ROOT = Path(__file__).resolve().parent.parent


class HoldoutTest(unittest.TestCase):
    def test_stable_and_about_twenty_percent(self):
        ids = [f"M{10000 + i}" for i in range(3000)]
        share = sum(in_holdout(i) for i in ids) / len(ids)
        self.assertTrue(0.17 < share < 0.23, share)
        self.assertEqual([in_holdout(i) for i in ids[:50]], [in_holdout(i) for i in ids[:50]])


class SuppressionListTest(unittest.TestCase):
    def test_rule(self):
        import soldouts.holdout as h
        orig = bs.in_holdout
        bs.in_holdout = lambda mid: False
        try:
            rows, held = bs.build(ctx(), "2026-11-13")
        finally:
            bs.in_holdout = orig
        deals = {r["deal_id"] for r in rows}
        self.assertIn("D1-1", deals)       # band B, open-ended
        self.assertNotIn("D2-1", deals)    # band A kept
        self.assertNotIn("D3-1", deals)    # do-not-contact: routing drops it anyway
        self.assertNotIn("D4-1", deals)    # schedule ends during the freeze
        self.assertIn("D5-1", deals)       # ends after the freeze
        self.assertTrue(all(r["reason"].startswith("auto-replenish") for r in rows))

    def test_holdout_merchants_never_suppressed(self):
        bs_in = bs.in_holdout
        bs.in_holdout = lambda mid: mid == "M1"
        try:
            rows, held = bs.build(ctx(), "2026-11-13")
        finally:
            bs.in_holdout = bs_in
        self.assertNotIn("D1-1", {r["deal_id"] for r in rows})
        self.assertEqual(held, ["D1-1"])


class DidTest(unittest.TestCase):
    def test_removes_a_gap_that_was_there_before(self):
        # holdout always 5 points better, before and after: no effect
        t_pre, h_pre = [0.0] * 30 + [1.0] * 70, [0.0] * 25 + [1.0] * 75
        est, lo, hi = measure._did_ci(t_pre, h_pre, t_pre, h_pre)
        self.assertEqual(est, 0)

    def test_finds_a_real_drop(self):
        t_pre, h_pre = [0.0] * 30 + [1.0] * 70, [0.0] * 30 + [1.0] * 70
        t_post = [0.0] * 60 + [1.0] * 40
        est, lo, hi = measure._did_ci(t_post, h_pre, t_pre, h_pre)
        self.assertAlmostEqual(est, -0.30)
        self.assertLess(hi, 0)


class MeasureTest(unittest.TestCase):
    def test_diff_ci_brackets_zero_for_same_data(self):
        xs = [float(i % 7) for i in range(200)]
        d, lo, hi = measure._diff_ci(xs, xs)
        self.assertEqual(d, 0)
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)


class StopRuleTest(unittest.TestCase):
    """The numbers Greg gets: restock 12 points (from week 6), GP £6 per sold-out (from week 8)."""
    def test_restock_line(self):
        self.assertEqual(measure.stop_check([-0.20, -0.3, -0.1], None, weeks_live=5), [])   # too early to read
        self.assertTrue(measure.stop_check([-0.13, -0.2, 0.0], None, weeks_live=6))
        self.assertEqual(measure.stop_check([-0.11, -0.2, 0.0], None, weeks_live=6), [])

    def test_gp_line(self):
        self.assertEqual(measure.stop_check(None, [-8.0, -12, -4], weeks_live=7), [])        # too early to read
        self.assertTrue(measure.stop_check(None, [-6.5, -10, -3], weeks_live=8))
        self.assertEqual(measure.stop_check(None, [-5.5, -10, -1], weeks_live=8), [])

    def test_callback_count_on_todays_routing_input(self):
        res = measure.callbacks(ROOT / "routing" / "input" / "todays_soldouts.csv", ROOT / "proposal" / "env_overrides.json")
        self.assertEqual((res["tasks"], res["promised_callbacks"], res["tasks_on_listed_deals"]), (36, 3, 3))
        self.assertEqual(res["callbacks_dropped"], [])


if __name__ == "__main__":
    unittest.main()
