"""Which merchants are held out of the routing change. Stable: same merchant, same answer, every run."""
import hashlib

HOLDOUT_PCT = 20


def in_holdout(merchant_id, pct=HOLDOUT_PCT, salt="soldout-suppression-2026-11"):
    h = int(hashlib.sha256(f"{salt}:{merchant_id}".encode()).hexdigest(), 16)
    return h % 100 < pct
