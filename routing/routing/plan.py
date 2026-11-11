"""Build the morning task list for one rep."""
import csv
import json
import sys
from pathlib import Path

from routing.suppressions import load_suppressions

ROOT = Path(__file__).resolve().parent.parent

# Used when a key is missing from config/routing.json.
DEFAULTS = {
    "suppressed_deal_ids": [],
    "suppress_soldout_tasks": False,
    "suppression_file": "input/suppressions.csv",
}


def load_overrides():
    return json.loads((ROOT / "config" / "env_overrides.json").read_text())


def load_config():
    config = dict(DEFAULTS)
    config.update(json.loads((ROOT / "config" / "routing.json").read_text()))
    config.update(load_overrides().get("routing", {}))
    return config


def load_priors():
    priors = json.loads((ROOT / "priors.json").read_text())
    priors.update(load_overrides().get("priors", {}))
    return priors


def load_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def expected_gp(row, priors):
    p = priors["restock"]
    return (p["called"] - p["left_alone"]) * float(row["value_30d_gbp"])


def suppression_on(config):
    """The sold-out suppression switch. Only a real JSON true turns it on.

    A string such as "false" in env_overrides.json would be truthy in Python, so we
    compare with `is True` on purpose: anything unexpected means off.
    """
    return config.get("suppress_soldout_tasks") is True


def load_suppression_sets(config):
    """(deal_ids, merchant_ids) to leave out, or (set(), set()) when the switch is off."""
    if not suppression_on(config):
        return set(), set()
    rows = load_suppressions(ROOT / config["suppression_file"])
    return ({r["deal_id"] for r in rows if r["deal_id"]},
            {r["merchant_id"] for r in rows if r["merchant_id"] and not r["deal_id"]})


def is_suppressed(row, suppressions):
    """Sold-out suppression. Never applies to a promised callback: someone told the merchant we'd ring."""
    deals, merchants = suppressions
    if row["callback_promised"] == "1":
        return False
    return row["deal_id"] in deals or row["merchant_id"] in merchants


def is_active(row, config, suppressions=(frozenset(), frozenset())):
    if row["do_not_contact"] == "1":
        return False
    if row["deal_id"] in set(config.get("suppressed_deal_ids", [])):
        return False
    if is_suppressed(row, suppressions):
        return False
    return True


def build_plan(rows, priors=None, config=None, suppressions=None):
    """Return (today's list, carried over). Each item is a dict with task and rank details.

    With suppress_soldout_tasks off (the default) the output is exactly what 2.15.0 produced.
    """
    priors = priors or load_priors()
    config = config or load_config()
    if suppressions is None:
        suppressions = load_suppression_sets(config)
    active = [r for r in rows if is_active(r, config, suppressions)]
    promised = [r for r in active if r["callback_promised"] == "1"]
    rest = [r for r in active
            if r["callback_promised"] != "1" and int(r["failed_attempts"]) < config["max_failed_attempts"]]
    rest.sort(key=lambda r: expected_gp(r, priors), reverse=True)

    today, carried, minutes = [], [], 0
    for r in promised + rest:
        item = {
            "task_id": r["task_id"], "merchant_id": r["merchant_id"], "merchant_name": r["merchant_name"],
            "deal_id": r["deal_id"], "reason": "callback" if r in promised else "restock",
            "expected_gp": round(expected_gp(r, priors), 2),
        }
        if minutes + config["minutes_per_task"] <= config["minutes_per_day"]:
            today.append(item)
            minutes += config["minutes_per_task"]
        else:
            carried.append(item)
    return today, carried


if __name__ == "__main__":
    rows = load_rows(sys.argv[1])
    config = load_config()
    suppressions = load_suppression_sets(config)
    if suppression_on(config):
        n = sum(1 for r in rows if is_suppressed(r, suppressions))
        print(f"sold-out suppression ON: {n} task(s) not created", file=sys.stderr)
    today, carried = build_plan(rows, config=config, suppressions=suppressions)
    for item in today:
        print(item["task_id"], item["merchant_name"], item["reason"], item["expected_gp"])
    print(f"carried over: {len(carried)}")
