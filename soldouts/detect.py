"""Read the free text about a merchant and flag what matters for a sold-out, with the quote behind each flag.

Two backends, same output:
- rules: regular expressions. Runs offline, free, deterministic. Misses nuance.
- llm:   the sandbox LLM gateway (Anthropic Messages API). Reads context ("booked solid" after a
         cap raise is good news; "can't fit them in" is not). Needs SANDBOX_KEY and costs money,
         so results are cached in data/flags_llm.json and the tool reads the cache.

Every flag carries a quote, and the quote is checked in code: it must appear word for word in
the item it cites. A flag whose quote can't be found is dropped (the LLM made it up or paraphrased).

    python3 -m soldouts.detect --backend rules --pack data/pack --merchants M10001,M10002
    python3 -m soldouts.detect --backend llm --merchants-from-today --out data/flags_llm.json
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

from soldouts import config, texts

FLAGS = {
    "capacity_limit": "Merchant can't serve more customers: fully booked for weeks, long waits, no availability before expiry, tiny team. Raising the cap risks refunds.",
    "no_restock_wanted": "Merchant has said they don't want to restock or be called: sold out on purpose, declined, cutting back, 'don't call'.",
    "auto_topup": "Merchant says the cap tops itself up (auto top-up / refreshes itself), so no call is needed.",
    "wants_more": "Merchant wants more volume or a higher cap: 'increase it', 'go to 85', 'heaving', asked for a call to raise.",
    "alert_link_trouble": "Merchant couldn't use the Deal Alert link: login/password problems, link looked dodgy, not sure it worked.",
    "quality_risk": "Customers report service failures: cancelled bookings, no answer, dirty, broken, rude. More volume would make it worse.",
    "temporarily_away": "Merchant is closed or away for a period (holiday, refurbishment, illness). Call later, not now.",
}

RULES = {
    "capacity_limit": r"can'?t (cope|fit (them|anyone|more)|take (any )?more)|fully booked|full (this month|until|to|for)|"
                      r"waiting \d+ weeks|wait(ed)? \d+ weeks|no availability|nothing available|next (gap|appointment|slot)|"
                      r"\d+ weeks out|one[- ]person|tiny team|double[- ]booked|couldn'?t get an? ap+ointment|"
                      r"capping bookings|diary (is )?full",
    "no_restock_wanted": r"don'?t call|stay sold out|sold out on purpose|this is deliberate|leave (things|it) as (they are|it is)|"
                         r"^declined|not renewing|cutting back|don'?t send|no ta\b",
    "auto_topup": r"auto[- ]?top[- ]?up|refreshes itself|tops? (itself )?up automatically|auto[- ]?replenish",
    "wants_more": r"increase it|\bgo (up )?to \d+|up the cap|raise (it|the cap)|heaving|yes,? (please )?top up|top (it )?up please|"
                  r"more vouchers|cap (lifted|raised|now) to \d+",
    "alert_link_trouble": r"log ?in|password|looks dodgy|not clicking|clicked (the|your) (link|button).*(twice|assume|hope)|link.*(didn'?t|doesn'?t|not) work",
    "quality_risk": r"\bdirty\b|\bbroken\b|cancell?ed (on the day|with no)|never answered|emails? ignored|\brude\b|"
                    r"code (wasn'?t|was not) recognised|no[- ]show(ed)? (by|from) (the )?(merchant|staff)",
    "temporarily_away": r"out of (the )?office|on (a )?(course|holiday|leave)|back (on )?(mon|tue|wed|thu|fri|sat|sun)|"
                        r"\bshut until\b|in hospital|gone (fishing|away)|redecorat|closed (for|until)",
}
_COMPILED = {k: re.compile(v, re.I | re.M) for k, v in RULES.items()}


def _sentence_around(text, start, end):
    """The sentence containing a match, so the quote reads on its own."""
    left = max(text.rfind(c, 0, start) for c in ".!?\n")
    right_candidates = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left + 1:right].strip()


def rules_backend(items):
    flags = []
    for it in items:
        if it["source"] == "review" and it.get("rating") and it["rating"] >= 4:
            continue  # a happy review doesn't flag a risk
        for flag, rx in _COMPILED.items():
            if it["source"] != "review" and flag == "quality_risk" and it["source"] != "refund_reason":
                continue
            m = rx.search(it["text"])
            if m:
                flags.append({"flag": flag, "item_id": it["id"], "source": it["source"], "date": it["date"],
                              "quote": _sentence_around(it["text"], m.start(), m.end())})
    return flags


SYSTEM = """You help a Groupon UK sales team decide whether a sold-out deal is worth a restock call.
You read everything written about ONE merchant (rep notes, the merchant's replies to Deal Alert emails,
customer reviews, refund reasons) and flag only what is clearly supported by the text.

Flags:
{flags}

Rules:
- Each flag must cite one item by its id and quote the exact words from that item (copy them character
  for character, 5 to 40 words). No paraphrase. If you can't quote it, don't flag it.
- Prefer recent items. Later items override earlier ones (a merchant who was full in spring may want more now).
- "Booked solid" or "busy" after the rep raised the cap is demand, not a capacity problem.
- One-off customer mistakes (bought twice, changed mind, gift not wanted) are not quality_risk.
- Return at most one flag per type: the strongest, most recent evidence.
- Then give a one-line verdict for the rep: call / don't call / something else, and why."""

SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {"type": "array", "items": {
            "type": "object",
            "properties": {"flag": {"type": "string", "enum": list(FLAGS)}, "item_id": {"type": "string"},
                           "quote": {"type": "string"}},
            "required": ["flag", "item_id", "quote"], "additionalProperties": False}},
        "verdict": {"type": "string"},
    },
    "required": ["flags", "verdict"], "additionalProperties": False,
}


def _llm_call(payload, key, base, retries=4):
    req = urllib.request.Request(base.rstrip("/") + "/llm/v1/messages", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "anthropic-version": "2023-06-01"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 402:
                raise SystemExit(f"LLM budget used up: {body}")
            if e.code in (429, 503, 529) and attempt < retries - 1:
                time.sleep(int(e.headers.get("Retry-After") or 2 ** (attempt + 1)))
                continue
            raise RuntimeError(f"LLM {e.code}: {body}")


def llm_backend(items, model="claude-haiku-5-5", max_items=60, call=None):
    """Flags for ONE merchant's items. `call` can be swapped for a fake in tests."""
    items = sorted(items, key=lambda i: i["date"], reverse=True)[:max_items]
    if not items:
        return [], ""
    lines = "\n".join(f"[{i['id']}] {i['date']} {i['source']}"
                      + (f" rating={i['rating']}" if i.get("rating") else "") + f": {i['text']}" for i in items)
    payload = {
        "model": model, "max_tokens": 1500, "thinking": {"type": "disabled"},
        "system": SYSTEM.format(flags="\n".join(f"- {k}: {v}" for k, v in FLAGS.items())),
        "messages": [{"role": "user", "content": f"Items about this merchant, newest first:\n{lines}"}],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    if call is None:
        config.load_env_file()
        key = os.environ.get("SANDBOX_KEY")
        base = os.environ.get("SANDBOX_BASE", "https://desk-production-6adc.up.railway.app/api/sandbox/v1")
        if not key:
            raise SystemExit("SANDBOX_KEY not set (put it in .env). Use --backend rules to run offline.")
        call = lambda p: _llm_call(p, key, base)
    resp = call(payload)
    if resp.get("stop_reason") != "end_turn":
        raise RuntimeError(f"LLM stopped with {resp.get('stop_reason')}, not parsing a partial answer")
    text = "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
    out = json.loads(text)
    by_id = {i["id"]: i for i in items}
    flags = []
    for f in out["flags"]:
        it = by_id.get(f["item_id"])
        if it:
            flags.append({**f, "source": it["source"], "date": it["date"]})
    return flags, out.get("verdict", "")


def _norm(s):
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')).strip().lower()


def verify(flags, items):
    """Keep only flags whose quote is really in the cited item. Returns (kept, dropped)."""
    by_id = {i["id"]: i for i in items}
    kept, dropped = [], []
    for f in flags:
        it = by_id.get(f["item_id"])
        quote = f["quote"].strip().strip('"').rstrip(".…")
        ok = it is not None and len(quote) >= 8 and _norm(quote) in _norm(it["text"])
        (kept if ok else dropped).append(f)
    return kept, dropped


def recent(items, today, max_age_days=config.SIGNAL_MAX_AGE_DAYS):
    cutoff = (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()
    return [i for i in items if i["date"] >= cutoff]


def detect(items_by_merchant, backend="rules", today=None, **kw):
    """{merchant_id: {"flags": [...], "dropped": [...], "verdict": str}}"""
    today = today or date.today().isoformat()
    out = {}
    for mid, items in items_by_merchant.items():
        items = recent(items, today)
        if backend == "llm":
            raw, verdict = llm_backend(items, **kw)
        else:
            raw, verdict = rules_backend(items), ""
        kept, dropped = verify(raw, items)
        out[mid] = {"flags": kept, "dropped": dropped, "verdict": verdict, "backend": backend}
    return out


def group(items):
    g = defaultdict(list)
    for i in items:
        g[i["merchant_id"]].append(i)
    return g


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["rules", "llm"], default="rules")
    ap.add_argument("--pack", default=str(config.PACK), help="folder with rep_notes.csv, deal_alert_replies.csv, reviews.csv, refunds.csv")
    ap.add_argument("--merchants", help="comma-separated merchant ids (default: all with text)")
    ap.add_argument("--today", default=date.today().isoformat(), help="YYYY-MM-DD; text older than a year is ignored")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--out", help="write JSON here (default: stdout)")
    ap.add_argument("--merge", action="store_true", help="merge into an existing --out file instead of replacing it")
    a = ap.parse_args(argv)
    ids = set(a.merchants.split(",")) if a.merchants else None
    items = group(texts.load(a.pack, ids))
    kw = {"model": a.model} if a.backend == "llm" else {}
    existing = {}
    if a.out and a.merge and os.path.exists(a.out):
        existing = json.load(open(a.out))
        items = {k: v for k, v in items.items() if k not in existing}
    result = {}
    for n, (mid, its) in enumerate(items.items(), 1):
        try:
            result.update(detect({mid: its}, a.backend, a.today, **kw))
        except RuntimeError as e:
            print(f"{mid}: {e}", file=sys.stderr)
        if a.backend == "llm":
            print(f"{n}/{len(items)} {mid}: {len(result.get(mid, {}).get('flags', []))} flags", file=sys.stderr)
    result = {**existing, **result}
    js = json.dumps(result, indent=1, ensure_ascii=False)
    if a.out:
        open(a.out, "w").write(js)
        print(f"wrote {a.out}: {len(result)} merchants", file=sys.stderr)
    else:
        print(js)


if __name__ == "__main__":
    main()
