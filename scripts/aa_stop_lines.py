"""How often would the stop lines fire by chance? An A/A test on history, with no change at all.

    python3 scripts/aa_stop_lines.py            # a fake launch every day
    python3 scripts/aa_stop_lines.py --step 7   # every week (faster, rougher)

For every fake launch date it runs the Monday checks the way `soldouts.measure readout` does them live:
listed deals (treated) minus holdout, minus the same gap in the 12 weeks before launch, counting only
sold-outs whose outcome window is over (14 days for restock, 30 for GP). Restock is checked from week 6,
GP from week 8, up to --weeks. A launch counts as "stopped" if any of its checks crosses the line.

It prints the share of single checks and of launches that cross each candidate line, over the whole
history and for launches made at this time of year last year (20 Oct to 1 Dec 2025), when the two
groups drifted apart by themselves. Needs the data pack in data/pack.
"""
import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soldouts import measure  # noqa: E402

SEASON = (date(2025, 10, 20), date(2025, 12, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="data/pack")
    ap.add_argument("--step", type=int, default=1, help="days between fake launches")
    ap.add_argument("--weeks", type=int, default=16, help="last Monday check, in weeks after launch")
    a = ap.parse_args()

    rows = measure.eligible_soldouts(a.pack, "2025-01-01", "2026-12-31")
    first = date.fromisoformat(min(r["sold_out_date"] for r in rows))
    last = date.fromisoformat(max(r["sold_out_date"] for r in rows if r["gp_30d_after_gbp"]))
    # per day and group: restocked sum, n, GP sum, n with GP
    agg = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for r in rows:
        rs, gp = measure._outcomes([r], 14)
        x = agg[(r["sold_out_date"], r["holdout"])]
        x[0] += rs[0]
        x[1] += 1
        if gp:
            x[2] += gp[0]
            x[3] += 1

    def gap(s, e, k):
        out = []
        for hold in (False, True):
            t = [0.0, 0, 0.0, 0]
            d = s
            while d <= e:
                x = agg.get((d.isoformat(), hold))
                if x:
                    t = [t[i] + x[i] for i in range(4)]
                d += timedelta(days=1)
            out.append(t[0] / t[1] if k == "restock" else t[2] / t[3])
        return out[0] - out[1]

    sched = {"restock": (measure.RESTOCK_FROM_WEEK, 14), "gp": (measure.GP_FROM_WEEK, measure.GP_WINDOW_D)}
    launches = []
    s = first + timedelta(weeks=12)
    while s + timedelta(days=7 * measure.RESTOCK_FROM_WEEK - 14) <= last:
        pre = (s - timedelta(weeks=12), s - timedelta(days=1))
        reads = {}
        for k, (from_week, window) in sched.items():
            base = gap(*pre, k)
            reads[k] = [gap(s, e, k) - base
                        for w in range(from_week, a.weeks + 1)
                        for e in [s + timedelta(days=7 * w - window - 1)] if e <= last]
        launches.append((s, reads))
        s += timedelta(days=a.step)

    season = [x for x in launches if SEASON[0] <= x[0] <= SEASON[1]]
    print(f"{len(launches)} fake launches {launches[0][0]} to {launches[-1][0]}, checks to week {a.weeks}; "
          f"{len(season)} of them between {SEASON[0]} and {SEASON[1]}")
    lines = {"restock": [-0.10, -0.12, -0.14, -0.16, -0.18], "gp": [-5.0, -6.0, -7.0, -8.0, -9.0]}
    for k, cands in lines.items():
        allreads = [v for _, r in launches for v in r[k]]
        worst_season = min(v for _, r in season for v in r[k]) if season else None
        unit = (lambda v: f"{v * 100:+.1f} points") if k == "restock" else (lambda v: f"£{v:+.2f}")
        print(f"\n{k}: {len(allreads)} checks, worst {unit(min(allreads))}; worst at this time last year {unit(worst_season)}")
        for line in cands:
            reads = sum(v < line for v in allreads) / len(allreads)
            with_reads = [x for x in launches if x[1][k]]
            stopped = sum(any(v < line for v in r[k]) for _, r in with_reads) / len(with_reads)
            st_season = sum(any(v < line for v in r[k]) for _, r in season) / len(season) if season else 0
            mark = "  <- in use" if line == (measure.STOP_RESTOCK if k == "restock" else measure.STOP_GP) else ""
            print(f"  line {unit(line):>14}: checks crossed {reads:5.1%}   launches stopped {stopped:4.0%}   "
                  f"launches at this time last year stopped {st_season:4.0%}{mark}")
    both = sum(any(v < measure.STOP_RESTOCK for v in r["restock"]) or any(v < measure.STOP_GP for v in r["gp"])
               for _, r in launches) / len(launches)
    both_season = sum(any(v < measure.STOP_RESTOCK for v in r["restock"]) or any(v < measure.STOP_GP for v in r["gp"])
                      for _, r in season) / len(season) if season else 0
    print(f"\nLines in use ({measure.STOP_RESTOCK * 100:.0f} points, £{measure.STOP_GP:.0f}): either one stopped "
          f"{both:.0%} of launches by chance, {both_season:.0%} of those at this time last year.")


if __name__ == "__main__":
    main()
