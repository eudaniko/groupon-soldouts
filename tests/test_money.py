import unittest

from soldouts import money

UPLIFT = {"bands": {"A": {"uplift_per_connected_call_gbp": 14.64, "connect_rate": 0.73},
                    "D": {"uplift_per_connected_call_gbp": 2.04, "connect_rate": 0.41}}}


class MoneyTest(unittest.TestCase):
    def test_rep_cost_is_minutes_times_rate(self):
        self.assertEqual(money.rep_cost(minutes=12, hourly=20), 4.0)
        self.assertEqual(money.rep_cost(minutes=30, hourly=30), 15.0)

    def test_value_formula(self):
        w = money.Worth(gp_if_connected=10, p_connect=0.5, refund_risk=0.2, rep_cost=1)
        self.assertAlmostEqual(w.value, 0.5 * 10 * 0.8 - 1)

    def test_small_merchant_not_worth_a_call_at_default_rate(self):
        w = money.worth("D", UPLIFT, p_connect=0.41, refund_share=0.1, hourly=20)
        self.assertLess(w.value, 0)

    def test_big_merchant_worth_a_call(self):
        w = money.worth("A", UPLIFT, p_connect=0.73, refund_share=0.05, hourly=20)
        self.assertGreater(w.value, 5)

    def test_refund_risk_share_and_capacity_doubling(self):
        self.assertAlmostEqual(money.refund_risk(10, 90), 0.1)
        self.assertAlmostEqual(money.refund_risk(10, 90, capacity_flag=True), 0.2)
        self.assertEqual(money.refund_risk(0, 0), 0.0)
        self.assertEqual(money.refund_risk(100, 0, capacity_flag=True), 0.9)  # capped

    def test_shrinkage_pulls_small_samples_to_band(self):
        self.assertAlmostEqual(money.shrunk_rate(0, 0, 0.7), 0.7)
        self.assertAlmostEqual(money.shrunk_rate(1, 1, 0.5, prior_weight=1), 0.75)
        self.assertAlmostEqual(money.shrunk_rate(100, 100, 0.5), 102.5 / 105)

    def test_explain_shows_the_sum(self):
        w = money.Worth(10, 0.5, 0.0, 1.0)
        self.assertIn("= £4.00", w.explain())


if __name__ == "__main__":
    unittest.main()
