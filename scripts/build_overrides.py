"""Write proposal/env_overrides.json: today's config/env_overrides.json, unchanged line for line,
plus a "routing" block with suppressed_deal_ids. Also writes proposal/env_overrides.diff, the
change Hana reviews (only added lines, plus a comma).

routing.json's suppressed_deal_ids is REPLACED by the override, so the ids already there are kept first.

    python3 scripts/build_overrides.py
"""
import csv
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "routing" / "config" / "env_overrides.json"
ROUTING = ROOT / "routing" / "config" / "routing.json"
LIST = ROOT / "proposal" / "suppressions.csv"
OUT = ROOT / "proposal" / "env_overrides.json"
DIFF = ROOT / "proposal" / "env_overrides.diff"
NOTE = ("2026-11 sold-out suppression (config-only). Off = deploy this file without the 'routing' key. "
        "Keeps the 3 ids from routing.json. List and reasons: proposal/suppressions.csv")


def build():
    text = CURRENT.read_text()
    existing = json.loads(ROUTING.read_text())["suppressed_deal_ids"]
    listed = [r["deal_id"] for r in csv.DictReader(open(LIST, newline=""))]
    ids = existing + [d for d in listed if d not in existing]
    body = text.rstrip()
    assert body.endswith("}"), "unexpected env_overrides.json layout"
    new = (body[:-1].rstrip() + ",\n"
           f'  "_comment_soldouts": {json.dumps(NOTE)},\n'
           '  "routing": {\n    "suppressed_deal_ids": [\n'
           + ",\n".join(f'      "{d}"' for d in ids)
           + "\n    ]\n  }\n}\n")
    json.loads(new)  # still valid JSON
    diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                        "a/config/env_overrides.json", "b/config/env_overrides.json"))
    return new, diff, ids


if __name__ == "__main__":
    new, diff, ids = build()
    OUT.write_text(new)
    DIFF.write_text(diff)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(ids)} ids) and {DIFF.relative_to(ROOT)}")
