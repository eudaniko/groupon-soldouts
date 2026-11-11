"""How we'll know if it worked.

    python3 -m soldouts.measure estimate                     # the range now, from history
    python3 -m soldouts.measure readout --start 2026-11-14   # the real number, holdout vs treated

Design: merchants are split 80/20 by a stable hash (soldouts/holdout.py). For the 80%, sold-outs on
deals with a running auto-replenish schedule (bands B-D) get no rep task; the 20% keep getting them.
The readout compares the two groups on the same kind of sold-out, so seasonality and peak hit both.

What it reads (offline, from files): sold_out_deals.csv, activities.csv, auto_replenish_schedules.csv,
merchants.csv. Point --pack at a fresh export (or the sandbox dump) after launch.
"""
import argparse
import csv
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from soldouts import config, money
from soldouts.holdout import in_holdout

MIN_PER_TASK = config.MINUTES_PER_TASK


def _rows(pack, name):
    with open(Path(pack) / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def eligible_soldouts(pack, start, end, bands=config.AUTO_SKIP_BANDS):
    merchants = {r["merchant_id"]: r for r in _rows(pack, "merchants.csv")}
    sched = defaultdict(list)
    for r in _rows(pack, "auto_replenish_schedules.csv"):
        sched[r["deal_id"]].append(r)
    out = []
    for r in _rows(pack, "sold_out_deals.csv"):
        d = r["sold_out_date"]
        if not (start <= d <= end):
            continue
        m = merchants.get(r["merchant_id"])
        if not m or m["size_band"] not in bands or m["do_not_contact"] == "1":
            continue
        if any(s["start_date"] <= d and (not s["end_date"] or s["end_date"] >= d) for s in sched[r["deal_id"]]):
            out.append({**r, "band": m["size_band"], "holdout": in_holdout(r["merchant_id"])})
    return out


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _mean_ci(xs, n=1000, seed=1):
    if len(xs) < 2:
        return (statistics.fmean(xs) if xs else float("nan"), float("nan"), float("nan"))
    rnd = random.Random(seed)
    means = sorted(statistics.fmean(rnd.choices(xs, k=len(xs))) for _ in range(n))
    return statistics.fmean(xs), means[int(n * .05)], means[int(n * .95)]


def _diff_ci(a, b, n=1000, seed=1):
    rnd = random.Random(seed)
    ds = sorted(statistics.fmean(rnd.choices(a, k=len(a))) - statistics.fmean(rnd.choices(b, k=len(b))) for _ in range(n))
    return statistics.fmean(a) - statistics.fmean(b), ds[int(n * .05)], ds[int(n * .95)]


def estimate(pack, start="2025-10-01", end="2026-09-30", hourly=None):
    uplift = config.load_uplift()
    rows = eligible_soldouts(pack, start, end)
    weeks = _days(start, end) / 7
    treated = [r for r in rows if not r["holdout"]]
    acts = _rows(pack, "activities.csv")
    connected = {a["sold_out_id"] for a in acts if a["sold_out_id"] and a["type"] == "call"
                 and a["duration_s"] and float(a["duration_s"]) >= 120}
    # GP at risk: the connected calls that happened on these sold-outs, times what such a call adds.
    lo = hi = mid = 0.0
    for r in treated:
        if r["sold_out_id"] in connected:
            b = uplift["bands"][r["band"]]
            mid += b["uplift_when_auto_replenish_gbp"]
            lo += b["uplift_when_auto_ci90"][1]   # pessimistic: calls were worth the most
            hi += b["uplift_when_auto_ci90"][0]
    per_week = len(treated) / weeks
    hours = per_week * MIN_PER_TASK / 60
    # Freed slots go to the next task on the list (carry-over). What's that worth? Our model's
    # value for a typical band A/B manual sold-out, ranging from "rep time just disappears" (£0)
    # to the band-A value.
    rc = money.rep_cost(hourly=hourly)
    vals = {b: uplift["bands"][b]["connect_rate"] * uplift["bands"][b]["uplift_per_connected_call_gbp"] for b in "AB"}
    redeploy_hi = max(vals["A"] - 0, 0)  # rep cost already paid: the rep was going to work those minutes anyway
    redeploy_lo = 0.0
    return {
        "period": [start, end],
        "suppressed_tasks_per_week": round(per_week, 1),
        "rep_hours_freed_per_week": round(hours, 1),
        "gp_lost_per_year_gbp": {"central": round(mid / weeks * 52), "worst": round(lo / weeks * 52), "best": round(hi / weeks * 52)},
        "gp_from_redeployed_time_per_year_gbp": {"low": round(per_week * redeploy_lo * 52), "high": round(per_week * redeploy_hi * 52)},
        "assumptions": {"rep_hourly_cost_gbp": config.REP_HOURLY_COST_GBP if hourly is None else hourly,
                        "holdout_pct": 20, "bands": sorted(config.AUTO_SKIP_BANDS)},
    }


def readout(pack, start, end=None, window_days=14):
    end = end or date.today().isoformat()
    rows = eligible_soldouts(pack, start, end)
    acts = defaultdict(int)
    for a in _rows(pack, "activities.csv"):
        if a["sold_out_id"]:
            acts[a["sold_out_id"]] += 1
    out = {}
    for name, grp in (("treated", [r for r in rows if not r["holdout"]]), ("holdout", [r for r in rows if r["holdout"]])):
        restocked = [1.0 if r["restocked_date"] and _days(r["sold_out_date"], r["restocked_date"]) <= window_days else 0.0 for r in grp]
        gp = [float(r["gp_30d_after_gbp"]) for r in grp if r["gp_30d_after_gbp"]]
        out[name] = {"n": len(grp), f"restocked_within_{window_days}d": round(statistics.fmean(restocked), 3) if grp else None,
                     "gp_30d_mean_gbp": [round(x, 2) for x in _mean_ci(gp)], "n_with_gp_30d": len(gp),
                     "with_rep_activity": sum(1 for r in grp if acts[r["sold_out_id"]])}
        out[name]["_gp"] = gp
        out[name]["_rs"] = restocked
    t, h = out["treated"], out["holdout"]
    if len(t["_gp"]) > 1 and len(h["_gp"]) > 1:
        out["gp_30d_diff_treated_minus_holdout_gbp"] = [round(x, 2) for x in _diff_ci(t["_gp"], h["_gp"])]
    if len(t["_rs"]) > 1 and len(h["_rs"]) > 1:
        out["restock_rate_diff"] = [round(x, 3) for x in _diff_ci(t["_rs"], h["_rs"])]
    out["rep_hours_saved"] = round(t["n"] * MIN_PER_TASK / 60, 1)
    for g in (t, h):
        del g["_gp"], g["_rs"]
    out["read_as"] = ("Rep hours saved is counted, not estimated. The change is safe if the GP difference's "
                      "90% interval stays above -£2 per sold-out and the restock rate gap stays within 5 points. "
                      "gp_30d is blank until 30 days after each sell-out.")
    return out


def main():
    import json
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--pack", default=str(config.PACK))
    r = sub.add_parser("readout")
    r.add_argument("--pack", default=str(config.PACK))
    r.add_argument("--start", required=True)
    r.add_argument("--end")
    a = ap.parse_args()
    res = estimate(a.pack) if a.cmd == "estimate" else readout(a.pack, a.start, a.end)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
