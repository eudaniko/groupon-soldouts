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


class MeasureTest(unittest.TestCase):
    def test_diff_ci_brackets_zero_for_same_data(self):
        xs = [float(i % 7) for i in range(200)]
        d, lo, hi = measure._diff_ci(xs, xs)
        self.assertEqual(d, 0)
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)


if __name__ == "__main__":
    unittest.main()
