"""Per-merchant context the tool needs, built once from the data pack.

    python3 -m soldouts.context      # writes data/context.json (committed, so the tool runs without the pack)
"""
import csv
import json
from collections import defaultdict

from soldouts import config


def _rows(name):
    with open(config.PACK / name, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def build():
    merchants = {r["merchant_id"]: {
        "name": r["merchant_name"], "category": r["category"], "city": r["city"], "region": r["region"],
        "band": r["size_band"], "rep_id": r["rep_id"], "do_not_contact": r["do_not_contact"] == "1",
        "restock_tasks_worked": 0, "restock_tasks_connected": 0, "gp_6m": 0.0, "refunds_6m": 0.0,
    } for r in _rows("merchants.csv")}

    # Restock-task outcomes, CRM replay duplicates removed, Deal Alert pseudo-calls (Feb 2026 migration) ignored.
    seen, worked, connected = set(), defaultdict(set), defaultdict(set)
    for r in _rows("activities.csv"):
        if not r["sold_out_id"] or r["subject"] == "Deal Alert sent":
            continue
        key = (r["merchant_id"], r["sold_out_id"], r["activity_date"], r["type"], r["owner_id"], r["duration_s"], r["subject"])
        if key in seen:
            continue
        seen.add(key)
        worked[r["merchant_id"]].add(r["sold_out_id"])
        if r["type"] == "call" and r["duration_s"] and float(r["duration_s"]) >= 120:
            connected[r["merchant_id"]].add(r["sold_out_id"])
    for mid, m in merchants.items():
        m["restock_tasks_worked"] = len(worked[mid])
        m["restock_tasks_connected"] = len(connected[mid])

    months = sorted({r["month"] for r in _rows("merchant_months.csv")})[-6:]
    for r in _rows("merchant_months.csv"):
        if r["month"] in months and r["merchant_id"] in merchants:
            merchants[r["merchant_id"]]["gp_6m"] += float(r["gp_gbp"] or 0)
            merchants[r["merchant_id"]]["refunds_6m"] += float(r["refunds_gbp"] or 0)

    schedules = defaultdict(list)
    for r in _rows("auto_replenish_schedules.csv"):
        schedules[r["deal_id"]].append({k: r[k] for k in ("schedule_id", "start_date", "end_date", "cadence", "top_up_qty", "created_by")})

    for m in merchants.values():
        m["gp_6m"], m["refunds_6m"] = round(m["gp_6m"], 2), round(m["refunds_6m"], 2)
    return {"months": months, "merchants": merchants, "schedules": schedules}


def load():
    return json.loads((config.DATA / "context.json").read_text())


def active_schedule(schedules, deal_id, on_date):
    """The auto-replenish schedule running on this deal on this date (YYYY-MM-DD), or None."""
    for s in schedules.get(deal_id, []):
        if s["start_date"] <= on_date and (not s["end_date"] or s["end_date"] >= on_date):
            return s
    return None


if __name__ == "__main__":
    ctx = build()
    (config.DATA / "context.json").write_text(json.dumps(ctx, separators=(",", ":")))
    print(f"wrote data/context.json: {len(ctx['merchants'])} merchants, {len(ctx['schedules'])} deals with schedules")
