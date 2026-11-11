"""What should the rep do about each sold-out, and why. Deterministic: text flags feed in, code decides.

Order of checks (first match wins):
 1. do-not-contact merchant            -> skip
 2. rep promised a callback            -> call (we said we would)
 3. rep marked the merchant            -> follow the mark
 4. auto-replenish running (bands B-D) -> skip, it tops up by itself
 5. merchant said no / sold out on purpose -> skip, quote
 6. merchant away                      -> later, quote
 7. capacity or quality problem        -> call, but don't push a cap raise; talk capacity
 8. Deal Alert link trouble            -> something else: send login help (2 min), not a sales call
 9. expected value > threshold         -> call, worth ~£X
10. otherwise                          -> don't bother, worth less than the rep's time
"""
from dataclasses import dataclass, field, asdict

from soldouts import config, money
from soldouts.context import active_schedule

CALL, SKIP, LATER, OTHER = "call", "skip", "later", "other"

# Marks a rep can set (kept short: they're the sandbox mark codes too).
MARKS = {
    "no_call": "Don't call on sell-outs",
    "always_call": "Always call on sell-outs",
    "capacity": "Can't take more customers",
    "auto_ok": "Auto top-up handles it",
}


@dataclass
class Decision:
    action: str
    headline: str
    why: str
    value_gbp: float | None = None
    maths: str = ""
    quotes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _days_between(a, b):
    from datetime import date
    return abs((date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days)


MERCHANT_VOICE = {"rep_note", "alert_reply"}


def _quote(flags, *names):
    return [f for f in flags if f["flag"] in names]


def _strong(flags, *names):
    """Flags strong enough to act on.

    - One customer complaint is noise: a customer-side flag (review, refund reason) needs a second
      item, unless the rep or the merchant said it too.
    - A newer 'wants more' from the merchant or rep overrides older negative signals.
    """
    hits = _quote(flags, *names)
    if not hits:
        return []
    if not any(f["source"] in MERCHANT_VOICE for f in hits) and len(hits) < 2:
        return []
    newest_more = max((f["date"] for f in _quote(flags, "wants_more") if f["source"] in MERCHANT_VOICE), default="")
    if newest_more and newest_more > max(f["date"] for f in hits):
        return []
    return sorted(hits, key=lambda f: f["date"], reverse=True)


def decide(soldout, merchant, schedules, flags, uplift, mark=None, hourly=None):
    """soldout: dict with deal_id, merchant_id, sold_out_date (+ callback_promised optional).
    merchant: entry of context.json. flags: verified flags for this merchant (list)."""
    band = merchant["band"]
    bandinfo = uplift["bands"][band]
    p = money.shrunk_rate(merchant["restock_tasks_connected"], merchant["restock_tasks_worked"], bandinfo["connect_rate"])
    capacity = bool(_strong(flags, "capacity_limit"))
    w = money.worth(band, uplift, p, money.refund_risk(merchant["refunds_6m"], merchant["gp_6m"], capacity), hourly)
    v, maths = w.value, w.explain()

    if merchant.get("do_not_contact"):
        return Decision(SKIP, "Don't contact", "Merchant is on the do-not-contact list.")
    if str(soldout.get("callback_promised", "0")) == "1":
        return Decision(CALL, "Call: callback promised", "Someone told the merchant we'd ring.", v, maths)
    if mark:
        code, reason = mark.get("mark"), mark.get("reason", "")
        by = mark.get("marked_by", "a rep")
        if code == "no_call":
            return Decision(SKIP, "Don't call (rep's mark)", f"{by}: {reason}", v, maths)
        if code == "always_call":
            return Decision(CALL, f"Call (rep's mark), worth ~£{max(v, 0):.0f}", f"{by}: {reason}", v, maths)
        if code == "capacity":
            return Decision(SKIP, "Don't push a raise (rep's mark)", f"{by}: {reason}", v, maths)
        if code == "auto_ok":
            return Decision(SKIP, "Skip: auto top-up (rep's mark)", f"{by}: {reason}", v, maths)

    sched = active_schedule(schedules, soldout["deal_id"], soldout["sold_out_date"])
    if sched and band in config.AUTO_SKIP_BANDS:
        return Decision(SKIP, "Skip: tops up by itself",
                        f"Auto-replenish {sched['schedule_id']} adds {sched['top_up_qty']} {sched['cadence']}. "
                        f"In band {band}, {bandinfo['auto_restock_rate']:.0%} of these restock within "
                        f"~{bandinfo['auto_median_days_to_restock']:.0f} days without a call; a call adds "
                        f"~£{bandinfo['uplift_when_auto_replenish_gbp']:.2f}.", v, maths)

    if q := _strong(flags, "no_restock_wanted"):
        return Decision(SKIP, "Skip: merchant said no", "From the merchant's own words.", v, maths, q)
    q = [f for f in _strong(flags, "temporarily_away") if _days_between(f["date"], soldout["sold_out_date"]) <= 21]
    if q:
        newest = q[0]
        return Decision(LATER, "Later: merchant away", f"Last seen {newest['date']}. Check before calling.", v, maths, q)
    if q := _strong(flags, "capacity_limit", "quality_risk"):
        return Decision(CALL if v > config.MIN_CALL_VALUE_GBP else SKIP,
                        "Talk capacity, not a bigger cap",
                        "Text says they struggle to serve current volume. A bigger cap means refunds. "
                        "If you call: agree a daily booking limit or a longer voucher expiry instead.", v, maths, q)
    if q := _strong(flags, "alert_link_trouble"):
        return Decision(OTHER, "Send Deal Alert login help", "They tried the alert link and got stuck. "
                        "A 2-minute email fixes it for every future sell-out.", v, maths, q)
    if sched:  # band A with a schedule: keep the task, say so
        extra = f" Auto-replenish {sched['schedule_id']} is running too (band A: we still call; see README)."
    else:
        extra = ""
    if v > config.MIN_CALL_VALUE_GBP:
        return Decision(CALL, f"Call, worth ~£{v:.0f}", "Calls to this merchant connect and pay." + extra,
                        v, maths, _quote(flags, "wants_more"))
    return Decision(SKIP, "Don't bother", f"Worth ~£{v:.2f}: less than the rep's time." + extra, v, maths)
