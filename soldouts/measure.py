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

# Stop rule (Greg asked for numbers, not "credibly"). Effects are listed deals minus holdout,
# minus the same gap in the 12 weeks before launch. Each line is only checked once four weeks of
# sold-outs have had their full outcome window.
STOP_RESTOCK = -0.12      # 14-day restock rate, 12 points
STOP_GP = -6.0            # 30-day GP per sold-out, £6
RESTOCK_FROM_WEEK = 6     # 4 weeks of sold-outs + 14 days
GP_FROM_WEEK = 8          # 4 weeks of sold-outs + 30 days
GP_WINDOW_D = 30

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
    # The rep's minutes are paid either way, so a freed slot is worth what the next task on the
    # list earns: from nothing (time goes elsewhere) to a band-A manual call.
    redeploy_hi = vals["A"]
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


def list_volume(pack, list_path, weeks=12):
    """What the actual suppression list would have removed over the last `weeks` weeks of data."""
    uplift = config.load_uplift()
    listed = {r["deal_id"] for r in _rows(Path(list_path).parent, Path(list_path).name)}
    so = _rows(pack, "sold_out_deals.csv")
    last = max(r["sold_out_date"] for r in so)
    start = (date.fromisoformat(last) - timedelta(weeks=weeks)).isoformat()
    window = [r for r in so if start < r["sold_out_date"] <= last]
    hits = [r for r in window if r["deal_id"] in listed]
    bands = {r["merchant_id"]: r["size_band"] for r in _rows(pack, "merchants.csv")}
    connected = {a["sold_out_id"] for a in _rows(pack, "activities.csv") if a["sold_out_id"] and a["type"] == "call"
                 and a["duration_s"] and float(a["duration_s"]) >= 120}
    lost = [uplift["bands"][bands[r["merchant_id"]]] for r in hits if r["sold_out_id"] in connected]
    per_week = len(hits) / weeks
    return {
        "window": [start, last], "listed_deals": len(listed),
        "tasks_removed_per_week": round(per_week, 1),
        "share_of_all_tasks": round(len(hits) / len(window), 3),
        "rep_hours_per_week": round(per_week * MIN_PER_TASK / 60, 1),
        "gp_at_risk_per_year_gbp": {
            "central": round(sum(b["uplift_when_auto_replenish_gbp"] for b in lost) / weeks * 52),
            "worst": round(sum(b["uplift_when_auto_ci90"][1] for b in lost) / weeks * 52)},
    }


def _outcomes(rows, window_days):
    restocked = [1.0 if r["restocked_date"] and _days(r["sold_out_date"], r["restocked_date"]) <= window_days else 0.0
                 for r in rows]
    gp = [float(r["gp_30d_after_gbp"]) for r in rows if r["gp_30d_after_gbp"]]
    return restocked, gp


def _did_ci(t_post, h_post, t_pre, h_pre, n=1000, seed=1):
    """(treated - holdout) after launch minus the same gap before launch, with a 90% bootstrap interval.

    The holdout is picked by a hash, so the two groups are not identical and their gap moves around:
    about 0 over the whole history, but 'treated' restocked ~6 points less often (and made ~£4 less GP)
    from mid-November to early January last year, with no change at all. Subtracting the pre-launch gap
    removes most of that.
    """
    if min(len(t_post), len(h_post), len(t_pre), len(h_pre)) < 2:
        return None
    rnd = random.Random(seed)
    m = lambda xs: statistics.fmean(rnd.choices(xs, k=len(xs)))
    ds = sorted((m(t_post) - m(h_post)) - (m(t_pre) - m(h_pre)) for _ in range(n))
    f = statistics.fmean
    est = (f(t_post) - f(h_post)) - (f(t_pre) - f(h_pre))
    return [round(est, 3), round(ds[int(n * .05)], 3), round(ds[int(n * .95)], 3)]


def readout(pack, start, end=None, window_days=14, pre_weeks=12):
    """Holdout vs treated since `start`, corrected by the same comparison over the `pre_weeks` before it."""
    end = end or date.today().isoformat()
    pre_start = (date.fromisoformat(start) - timedelta(weeks=pre_weeks)).isoformat()
    pre_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    post, pre = eligible_soldouts(pack, start, end), eligible_soldouts(pack, pre_start, pre_end)
    end_d = date.fromisoformat(end)
    # Only sold-outs whose outcome window is over count (a deal that sold out 3 days ago can't have restocked "within 14 days" yet).
    cut = {"restock": (end_d - timedelta(days=window_days)).isoformat(),
           "gp": (end_d - timedelta(days=GP_WINDOW_D)).isoformat()}
    acts = defaultdict(int)
    for a in _rows(pack, "activities.csv"):
        if a["sold_out_id"]:
            acts[a["sold_out_id"]] += 1
    groups = {}
    for period, rows in (("post", post), ("pre", pre)):
        for name, hold in (("treated", False), ("holdout", True)):
            grp = [r for r in rows if r["holdout"] == hold]
            done = (lambda r, k: True) if period == "pre" else (lambda r, k: r["sold_out_date"] <= cut[k])
            rs, _ = _outcomes([r for r in grp if done(r, "restock")], window_days)
            _, gp = _outcomes([r for r in grp if done(r, "gp")], window_days)
            groups[(period, name)] = (rs, gp)
            groups[(period, name, "n")] = len(grp)
            groups[(period, name, "act")] = sum(1 for r in grp if acts[r["sold_out_id"]])
    out = {"window": {"pre": [pre_start, pre_end], "post": [start, end]}}
    for period in ("post", "pre"):
        out[period] = {}
        for name in ("treated", "holdout"):
            rs, gp = groups[(period, name)]
            out[period][name] = {
                "n": groups[(period, name, "n")],
                f"n_with_{window_days}d_outcome": len(rs),
                f"restocked_within_{window_days}d": round(statistics.fmean(rs), 3) if rs else None,
                "gp_30d_mean_gbp": [round(x, 2) for x in _mean_ci(gp)] if gp else None,
                "n_with_gp_30d": len(gp),
                "with_rep_activity": groups[(period, name, "act")],
            }
    g = groups
    out["restock_rate_effect"] = _did_ci(g[("post", "treated")][0], g[("post", "holdout")][0],
                                         g[("pre", "treated")][0], g[("pre", "holdout")][0])
    out["gp_30d_effect_gbp"] = _did_ci(g[("post", "treated")][1], g[("post", "holdout")][1],
                                       g[("pre", "treated")][1], g[("pre", "holdout")][1])
    out["rep_hours_saved"] = round(out["post"]["treated"]["n"] * MIN_PER_TASK / 60, 1)
    weeks_live = (end_d - date.fromisoformat(start)).days / 7
    out["weeks_live"] = round(weeks_live, 1)
    out["stop_if"] = {
        "restock_rate_effect_below": STOP_RESTOCK, "restock_checked_from_week": RESTOCK_FROM_WEEK,
        "gp_30d_effect_below_gbp": STOP_GP, "gp_checked_from_week": GP_FROM_WEEK,
    }
    out["stop_reasons"] = stop_check(out["restock_rate_effect"], out["gp_30d_effect_gbp"], weeks_live)
    out["stop_now"] = bool(out["stop_reasons"])
    out["read_as"] = ("Effects are [estimate, 90% low, 90% high]: listed deals minus holdout, minus the same gap in the "
                      "12 weeks before launch. Only sold-outs whose 14-day (restock) or 30-day (GP) window is over count. "
                      "Rep hours saved is counted, not estimated. On history with no change (a fake launch every week, "
                      "Aug 2025 to Sep 2026), the restock line was crossed by chance in 2-4% of reads and "
                      "the GP line in 2%.")
    return out


def stop_check(restock_effect, gp_effect, weeks_live):
    """The stop lines crossed, as sentences (empty = keep going). Effects are [estimate, low, high] or None."""
    out = []
    if weeks_live >= RESTOCK_FROM_WEEK and restock_effect and restock_effect[0] < STOP_RESTOCK:
        out.append(f"14-day restock rate {restock_effect[0] * 100:+.1f} points vs holdout (line: {STOP_RESTOCK * 100:.0f})")
    if weeks_live >= GP_FROM_WEEK and gp_effect and gp_effect[0] < STOP_GP:
        out.append(f"30-day GP per sold-out £{gp_effect[0]:+.2f} vs holdout (line: £{STOP_GP:.0f})")
    return out


def callbacks(input_csv, overrides_path):
    """Promised callbacks in a routing input file, and which of them the proposed list would drop."""
    import json
    rows = list(csv.DictReader(open(input_csv, newline="", encoding="utf-8")))
    listed = set(json.load(open(overrides_path))["routing"]["suppressed_deal_ids"])
    promised = [r for r in rows if r.get("callback_promised") == "1"]
    return {"tasks": len(rows), "promised_callbacks": len(promised),
            "tasks_on_listed_deals": sum(r["deal_id"] in listed for r in rows),
            "callbacks_dropped": [r["task_id"] for r in promised if r["deal_id"] in listed]}


def main():
    import json
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--pack", default=str(config.PACK))
    v = sub.add_parser("volume", help="what the actual suppression list removes, last 12 weeks")
    v.add_argument("--pack", default=str(config.PACK))
    v.add_argument("--list", default=str(config.ROOT / "proposal" / "suppressions.csv"))
    c = sub.add_parser("callbacks", help="promised callbacks the list would drop from a routing input file")
    c.add_argument("--input", default=str(config.ROOT / "routing" / "input" / "todays_soldouts.csv"))
    c.add_argument("--overrides", default=str(config.ROOT / "proposal" / "env_overrides.json"))
    r = sub.add_parser("readout")
    r.add_argument("--pack", default=str(config.PACK))
    r.add_argument("--start", required=True)
    r.add_argument("--end")
    a = ap.parse_args()
    if a.cmd == "estimate":
        res = estimate(a.pack)
    elif a.cmd == "volume":
        res = list_volume(a.pack, a.list)
    elif a.cmd == "callbacks":
        res = callbacks(a.input, a.overrides)
    else:
        res = readout(a.pack, a.start, a.end)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
