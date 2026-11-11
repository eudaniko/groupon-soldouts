"""Sold-out suppression list: deals or merchants whose sold-outs should not become rep tasks.

Agreed shape (Ops, October): one row per deal or merchant, read at start of run, only
when `suppress_soldout_tasks` is on in config. plan.py does not use it yet.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLUMNS = ["deal_id", "merchant_id", "reason", "source", "added_on"]


def load_suppressions(path=None):
    """Rows of the suppression file as dicts. A missing file means nothing is suppressed.

    A row needs a deal_id or a merchant_id (merchant-wide). `reason` and `source`
    are free text for the audit trail, e.g. "auto-replenish weekly" / "merchant_ops".
    """
    path = Path(path) if path else ROOT / "input" / "suppressions.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("deal_id", "merchant_id") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {', '.join(missing)}")
        rows = []
        for n, row in enumerate(reader, start=2):
            if not (row["deal_id"] or row["merchant_id"]):
                raise ValueError(f"{path.name} line {n}: needs a deal_id or a merchant_id")
            rows.append(row)
    return rows
