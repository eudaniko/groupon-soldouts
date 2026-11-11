"""Check the tool against a rep who knows the merchants.

    python3 -m soldouts.evaluate data/rep_labels.csv

rep_labels.csv: merchant_id, merchant_name, rep_says (ring|leave), rep_reason, labelled_by, labelled_on
For each merchant we compare the rep's ring/leave with (a) the tool's decision using the LLM flags,
(b) the tool's decision using the offline rules flags, (c) the LLM's own one-line verdict.
"""
import csv
import json
import sys

from soldouts import config, context, decide, detect, texts


def tool_says(action):
    return "ring" if action == decide.CALL else "leave"


def main(path, on_date="2026-11-10"):
    ctx, uplift = context.load(), config.load_uplift()
    llm = json.loads((config.DATA / "flags_llm.json").read_text()) if (config.DATA / "flags_llm.json").exists() else {}
    labels = list(csv.DictReader(open(path, newline="")))
    ids = {r["merchant_id"] for r in labels}
    rules = detect.detect(detect.group(texts.load(config.PACK, ids)), "rules", on_date) if config.PACK.exists() else {}
    agree = {"llm": 0, "rules": 0}
    print(f"{'merchant':32} {'rep':6} {'tool(llm)':10} {'tool(rules)':11} why (tool, llm flags)")
    for r in labels:
        m = ctx["merchants"][r["merchant_id"]]
        deal = next((d for d in ctx["schedules"] if d.startswith(r["merchant_id"].replace("M", "D", 1))), r["merchant_id"].replace("M", "D", 1) + "-1")
        so = {"deal_id": r.get("deal_id") or deal, "merchant_id": r["merchant_id"], "sold_out_date": on_date}
        a = decide.decide(so, m, ctx["schedules"], llm.get(r["merchant_id"], {}).get("flags", []), uplift)
        b = decide.decide(so, m, ctx["schedules"], rules.get(r["merchant_id"], {}).get("flags", []), uplift)
        rep = r["rep_says"].strip().lower()
        agree["llm"] += tool_says(a.action) == rep
        agree["rules"] += tool_says(b.action) == rep
        print(f"{m['name'][:32]:32} {rep:6} {tool_says(a.action):10} {tool_says(b.action):11} {a.headline}")
        print(f"{'':32} rep: {r['rep_reason']}")
    n = len(labels)
    print(f"\nagreement with {labels[0]['labelled_by'] if labels else 'rep'}: LLM flags {agree['llm']}/{n}, rules flags {agree['rules']}/{n}")


if __name__ == "__main__":
    main(*sys.argv[1:])
