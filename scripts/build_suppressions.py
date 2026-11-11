"""Build routing's input/suppressions.csv: deals whose sold-outs don't need a rep task.

Rule (v1, deliberately narrow): an auto-replenish schedule is running on the deal, with no end date
(or ending after the freeze), the merchant is size band B, C or D, and the merchant is not in the
20% holdout. Band A is left alone (too few data points to be sure calls don't pay there).

    python3 scripts/build_suppressions.py --on 2026-11-13 --out routing/input/suppressions.csv

Why open-ended schedules only: routing reads this file at the start of each run and the freeze
stops us regenerating it until 7 January. A schedule that ends during the freeze would otherwise
leave its deal suppressed with nothing topping it up.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from soldouts import config, context  # noqa: E402
from soldouts.holdout import in_holdout  # noqa: E402

FREEZE_END = "2027-01-07"


def build(ctx, on_date, bands=config.AUTO_SKIP_BANDS):
    rows, held = [], []
    for deal_id, scheds in sorted(ctx["schedules"].items()):
        s = context.active_schedule(ctx["schedules"], deal_id, on_date)
        if not s or (s["end_date"] and s["end_date"] <= FREEZE_END):
            continue
        mid = s["merchant_id"]
        m = ctx["merchants"].get(mid)
        if not m or m["band"] not in bands or m["do_not_contact"]:
            continue
        if in_holdout(mid):
            held.append(deal_id)
            continue
        rows.append({"deal_id": deal_id, "merchant_id": mid,
                     "reason": f"auto-replenish {s['schedule_id']} {s['cadence']} +{s['top_up_qty']}",
                     "source": "auto_replenish_schedules", "added_on": on_date})
    return rows, held


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--on", required=True, help="date the list is valid from (YYYY-MM-DD)")
    ap.add_argument("--out", default="routing/input/suppressions.csv")
    a = ap.parse_args()
    rows, held = build(context.load(), a.on)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["deal_id", "merchant_id", "reason", "source", "added_on"])
        w.writeheader()
        w.writerows(rows)
    print(f"{a.out}: {len(rows)} deals suppressed; {len(held)} eligible deals kept as holdout")


if __name__ == "__main__":
    main()
