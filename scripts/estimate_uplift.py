"""Re-check Priya's £11/call and estimate what a restock call is worth, by size band.

Needs pandas. Reads the data pack from data/pack/. Writes data/uplift.json, which the
tool reads (so the tool itself doesn't need pandas).

    python3 scripts/estimate_uplift.py

What it does differently from the memo:
1. Drops CRM sync-replay duplicates in activities.csv.
2. Splits out sold-outs whose deal had an auto-replenish schedule running that day
   (the memo assumed automation was negligible; it's ~19% of sold-outs).
3. Compares called vs left-alone sold-outs *of the same merchant* (merchant fixed effect),
   so "reps call merchants who'd have done well anyway" mostly drops out.
4. Weights by sold-outs, not by calls.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "pack"
PERIOD = ("2025-10-01", "2026-09-30")  # same 12 months as the memo


def load():
    s = pd.read_csv(D / "sold_out_deals.csv", parse_dates=["sold_out_date", "restocked_date"])
    m = pd.read_csv(D / "merchants.csv")
    a = pd.read_csv(D / "activities.csv", parse_dates=["activity_date"])
    a = a.drop_duplicates(["merchant_id", "sold_out_id", "activity_date", "type", "owner_id", "duration_s", "subject"])
    a = a[a.sold_out_id.notna()]
    connected = set(a[(a.type == "call") & (a.duration_s >= 120)].sold_out_id)
    # Feb 2026 CRM migration logged Deal Alert sends as 1-4s "calls" by reps: not rep activity.
    touched = set(a[a.subject != "Deal Alert sent"].sold_out_id)
    s = s.merge(m[["merchant_id", "size_band"]], on="merchant_id")
    s["group"] = np.where(s.sold_out_id.isin(connected), "called",
                          np.where(s.sold_out_id.isin(touched), "attempted", "left_alone"))
    sch = pd.read_csv(D / "auto_replenish_schedules.csv", parse_dates=["start_date", "end_date"])
    x = s[["sold_out_id", "deal_id", "sold_out_date"]].merge(sch[["deal_id", "start_date", "end_date"]], on="deal_id")
    x = x[(x.start_date <= x.sold_out_date) & (x.end_date.isna() | (x.end_date >= x.sold_out_date))]
    s["auto"] = s.sold_out_id.isin(x.sold_out_id)
    return s[(s.sold_out_date >= PERIOD[0]) & (s.sold_out_date <= PERIOD[1])].copy()


def within_merchant(d):
    d = d[d.group != "attempted"].dropna(subset=["gp_30d_after_gbp"]).copy()
    d["c"] = (d.group == "called").astype(float)
    g = d.groupby("merchant_id")
    y = d.gp_30d_after_gbp - g.gp_30d_after_gbp.transform("mean")
    c = d.c - g.c.transform("mean")
    return float((y * c).sum() / (c ** 2).sum()) if (c ** 2).sum() else 0.0


def bootstrap(d, n=200, seed=0):
    rng = np.random.default_rng(seed)
    groups = dict(tuple(d.groupby("merchant_id")))
    keys = np.array(list(groups))
    out = [within_merchant(pd.concat([groups[k] for k in rng.choice(keys, len(keys))])) for _ in range(n)]
    return [round(float(v), 2) for v in np.percentile(out, [5, 95])]


def main():
    s = load()
    print(f"sold-outs in memo period: {len(s)}")
    print(s.groupby("group").gp_30d_after_gbp.agg(["size", "mean"]).round(2), "\n")

    # Memo's number, reproduced: naive band difference weighted by calls.
    t = s.pivot_table(index="size_band", columns="group", values="gp_30d_after_gbp", aggfunc="mean")
    n = s.pivot_table(index="size_band", columns="group", values="sold_out_id", aggfunc="count")
    diff = t.called - t.left_alone
    memo = float((diff * n.called).sum() / n.called.sum())
    by_soldouts = float((diff * (n.called + n.left_alone)).sum() / (n.called + n.left_alone).sum())
    print(f"memo method (weighted by calls): £{memo:.2f}; weighted by sold-outs: £{by_soldouts:.2f}")

    print(f"share of sold-outs with auto-replenish running: {s.auto.mean():.1%}")
    out = {"period": PERIOD, "auto_share": round(float(s.auto.mean()), 3), "bands": {}}
    for band, d in s.groupby("size_band"):
        manual, auto = d[~d.auto], d[d.auto]
        worked = manual[manual.group != "left_alone"]
        row = {
            "uplift_per_connected_call_gbp": round(within_merchant(manual), 2),
            "uplift_ci90": bootstrap(manual),
            "uplift_when_auto_replenish_gbp": round(within_merchant(auto), 2),
            "uplift_when_auto_ci90": bootstrap(auto),
            "n_auto_called": int((auto.group == "called").sum()),
            "n_auto": int(len(auto)),
            "connect_rate": round(float((worked.group == "called").mean()), 3),
            "auto_restock_rate": round(float(auto.restocked_date.notna().mean()), 3),
            "auto_median_days_to_restock": float((auto.restocked_date - auto.sold_out_date).dt.days.median()),
        }
        out["bands"][band] = row
        print(band, row)
    (ROOT / "data" / "uplift.json").write_text(json.dumps(out, indent=2) + "\n")
    print("wrote data/uplift.json")


if __name__ == "__main__":
    main()
