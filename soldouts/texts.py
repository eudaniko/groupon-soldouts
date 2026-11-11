"""Load and clean the free text: rep notes, Deal Alert replies, reviews, refund reasons.

Known mess (data pack README): CRM sync replay duplicated notes with new ids; notes cut at
500 characters; Windows-1252 mojibake such as â€™ in a UTF-8 file; rep_id blank before 2025.
"""
import csv
from pathlib import Path

SOURCES = {
    # file: (source label, id column, date column, text column)
    "rep_notes.csv": ("rep_note", "note_id", "created_at", "text"),
    "deal_alert_replies.csv": ("alert_reply", "reply_id", "received_at", "text"),
    "reviews.csv": ("review", "review_id", "created_at", "text"),
    "refunds.csv": ("refund_reason", "refund_id", "created_at", "reason_text"),
}


def fix_mojibake(text):
    """Undo UTF-8 that was read as Windows-1252/Latin-1 (â€™ -> ’, Â£ -> £, emoji). Clean text is left alone.

    Each character is turned back into the byte it came from (cp1252 first, then Latin-1 for the
    control-range leftovers), and the bytes are decoded as UTF-8. If that doesn't decode cleanly the
    original text is kept, so a genuine "â" in a name isn't damaged.
    """
    if not any(ch in text for ch in "âÂÃð"):
        return text
    raw = bytearray()
    for ch in text:
        try:
            raw += ch.encode("cp1252")
        except UnicodeEncodeError:
            raw += bytes([ord(ch)]) if ord(ch) < 256 else ch.encode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Notes are cut at 500 chars, which can split a character at the very end.
        fixed = raw.decode("utf-8", errors="ignore")
        return fixed if len(fixed) >= len(text) * 0.8 else text


def load(folder, merchant_ids=None):
    """All text items as dicts: source, id, merchant_id, date, text (+ rating / amount when present)."""
    items, seen = [], set()
    for name, (source, id_col, date_col, text_col) in SOURCES.items():
        path = Path(folder) / name
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if merchant_ids and r["merchant_id"] not in merchant_ids:
                    continue
                text = fix_mojibake((r.get(text_col) or "").strip())
                if not text:
                    continue
                key = (source, r["merchant_id"], r[date_col], text)
                if key in seen:  # CRM sync replay: same merchant, time and text, new id
                    continue
                seen.add(key)
                item = {"source": source, "id": r[id_col], "merchant_id": r["merchant_id"],
                        "date": r[date_col][:10], "text": text, "truncated": source == "rep_note" and len(text) >= 500}
                if "rating" in r:
                    item["rating"] = int(r["rating"]) if r["rating"] else None
                if "amount_gbp" in r:
                    item["amount_gbp"] = float(r["amount_gbp"] or 0)
                items.append(item)
    return items
