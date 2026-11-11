import unittest

from soldouts import decide

UPLIFT = {"bands": {b: {"uplift_per_connected_call_gbp": g, "connect_rate": 0.7, "auto_restock_rate": 0.96,
                        "auto_median_days_to_restock": 7, "uplift_when_auto_replenish_gbp": 0.5}
                    for b, g in {"A": 14.64, "B": 8.18, "C": 4.09, "D": 2.04}.items()}}


def merchant(band="A", **kw):
    m = {"band": band, "do_not_contact": False, "restock_tasks_connected": 8, "restock_tasks_worked": 10,
         "gp_6m": 1000.0, "refunds_6m": 50.0}
    m.update(kw)
    return m


SO = {"deal_id": "D1-1", "merchant_id": "M1", "sold_out_date": "2026-11-10", "callback_promised": "0"}
SCHED = {"D1-1": [{"schedule_id": "AR-1", "start_date": "2026-01-01", "end_date": "", "cadence": "weekly",
                   "top_up_qty": "10", "created_by": "merchant_ops"}]}


def flag(name, source="alert_reply", date="2026-11-01", quote="some words here"):
    return {"flag": name, "source": source, "date": date, "quote": quote, "item_id": "X"}


def d(**kw):
    args = dict(soldout=SO, merchant=merchant(), schedules={}, flags=[], uplift=UPLIFT)
    args.update(kw)
    return decide.decide(**args)


class DecideTest(unittest.TestCase):
    def test_big_merchant_plain_case_is_a_call_with_value(self):
        r = d()
        self.assertEqual(r.action, decide.CALL)
        self.assertGreater(r.value_gbp, 0)
        self.assertIn("rep time", r.maths)

    def test_small_merchant_plain_case_is_dont_bother(self):
        self.assertEqual(d(merchant=merchant("D")).action, decide.SKIP)

    def test_do_not_contact_wins_over_everything(self):
        r = d(merchant=merchant(do_not_contact=True), soldout={**SO, "callback_promised": "1"})
        self.assertEqual(r.headline, "Don't contact")

    def test_callback_promised_is_always_a_call(self):
        r = d(merchant=merchant("D"), soldout={**SO, "callback_promised": "1"}, schedules=SCHED,
              flags=[flag("no_restock_wanted")])
        self.assertEqual(r.action, decide.CALL)

    def test_auto_replenish_skips_bands_b_to_d_but_not_a(self):
        self.assertEqual(d(merchant=merchant("B"), schedules=SCHED).headline, "Skip: tops up by itself")
        self.assertEqual(d(merchant=merchant("A"), schedules=SCHED).action, decide.CALL)

    def test_ended_schedule_does_not_skip(self):
        ended = {"D1-1": [{**SCHED["D1-1"][0], "end_date": "2026-10-01"}]}
        self.assertNotEqual(d(merchant=merchant("B"), schedules=ended).headline, "Skip: tops up by itself")

    def test_merchant_said_no_skips_with_quote(self):
        r = d(flags=[flag("no_restock_wanted", quote="happy to stay sold out")])
        self.assertEqual(r.action, decide.SKIP)
        self.assertEqual(r.quotes[0]["quote"], "happy to stay sold out")

    def test_one_customer_complaint_is_not_enough(self):
        self.assertEqual(d(flags=[flag("capacity_limit", source="review")]).action, decide.CALL)
        r = d(flags=[flag("capacity_limit", source="review"), flag("capacity_limit", source="refund_reason")])
        self.assertEqual(r.headline, "Talk capacity, not a bigger cap")

    def test_newer_wants_more_overrides_older_capacity(self):
        r = d(flags=[flag("capacity_limit", source="rep_note", date="2026-03-01"),
                     flag("wants_more", source="alert_reply", date="2026-10-01")])
        self.assertTrue(r.headline.startswith("Call, worth"))

    def test_away_only_counts_if_recent(self):
        recent = d(flags=[flag("temporarily_away", date="2026-11-05")])
        old = d(flags=[flag("temporarily_away", date="2026-06-05")])
        self.assertEqual(recent.action, decide.LATER)
        self.assertEqual(old.action, decide.CALL)

    def test_rep_mark_overrides_the_model(self):
        r = d(merchant=merchant("D"), mark={"mark": "always_call", "reason": "owner always says yes", "marked_by": "R10"})
        self.assertEqual(r.action, decide.CALL)
        r = d(mark={"mark": "no_call", "reason": "closing in December", "marked_by": "R10"})
        self.assertEqual(r.action, decide.SKIP)
        self.assertIn("closing in December", r.why)


if __name__ == "__main__":
    unittest.main()
