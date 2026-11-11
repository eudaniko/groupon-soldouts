import json
import unittest

from soldouts import detect, texts

ITEMS = [
    {"source": "alert_reply", "id": "DAR-1", "merchant_id": "M1", "date": "2026-10-01",
     "text": "Thanks, but this is deliberate. We're a tiny team and people waited 4 weeks. Happy to stay sold out."},
    {"source": "review", "id": "RV-1", "merchant_id": "M1", "date": "2026-09-01", "rating": 5,
     "text": "Lovely, can't fault it. Fully booked but worth the wait."},
    {"source": "rep_note", "id": "N-1", "merchant_id": "M1", "date": "2026-08-01",
     "text": "Merchant happy to go to 39. Said the spa day has brought loads of new faces in."},
]


def fake_llm(flags, stop="end_turn"):
    def call(payload):
        assert payload["thinking"] == {"type": "disabled"}
        return {"stop_reason": stop, "content": [{"type": "text", "text": json.dumps({"flags": flags, "verdict": "don't call"})}]}
    return call


class TextTest(unittest.TestCase):
    def test_mojibake_fixed(self):
        self.assertEqual(texts.fix_mojibake("theyâ€™ve"), "they’ve")
        self.assertEqual(texts.fix_mojibake("Â£50"), "£50")
        self.assertEqual(texts.fix_mojibake("theyâ\x80\x99ve"), "they’ve")
        self.assertEqual(texts.fix_mojibake("café, plain"), "café, plain")


class RulesTest(unittest.TestCase):
    def test_rules_find_flags_with_quotes_from_the_item(self):
        flags = detect.rules_backend(ITEMS)
        names = {f["flag"] for f in flags}
        self.assertIn("no_restock_wanted", names)
        self.assertIn("capacity_limit", names)
        self.assertIn("wants_more", names)
        for f in flags:
            self.assertIn(f["quote"], next(i["text"] for i in ITEMS if i["id"] == f["item_id"]))

    def test_happy_review_is_ignored(self):
        self.assertFalse([f for f in detect.rules_backend(ITEMS) if f["item_id"] == "RV-1"])


class LlmTest(unittest.TestCase):
    def test_made_up_quote_is_dropped(self):
        flags = [{"flag": "no_restock_wanted", "item_id": "DAR-1", "quote": "Happy to stay sold out"},
                 {"flag": "capacity_limit", "item_id": "DAR-1", "quote": "we cannot cope with demand"},  # not in text
                 {"flag": "wants_more", "item_id": "NOPE", "quote": "go to 39"}]                       # wrong id
        out = detect.detect({"M1": ITEMS}, backend="llm", today="2026-11-10", call=fake_llm(flags))["M1"]
        self.assertEqual([f["flag"] for f in out["flags"]], ["no_restock_wanted"])
        self.assertEqual(len(out["dropped"]), 1)  # wrong id never reaches verify; made-up quote is dropped

    def test_cut_off_answer_is_not_parsed(self):
        with self.assertRaises(RuntimeError):
            detect.llm_backend(ITEMS, call=fake_llm([], stop="max_tokens"))

    def test_old_text_ignored(self):
        old = [dict(ITEMS[0], date="2024-01-01")]
        self.assertEqual(detect.detect({"M1": old}, "rules", today="2026-11-10")["M1"]["flags"], [])


if __name__ == "__main__":
    unittest.main()


class OfflineFromFileTest(unittest.TestCase):
    """What a facilitator can run with no network and no key: the sample file + recorded LLM answers."""
    FIXTURE = "tests/fixtures/sample_items.json"

    def setUp(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        self.path = str(root / self.FIXTURE)
        self.items = json.load(open(self.path, encoding="utf-8"))
        self.recorded = json.load(open(root / "data" / "flags_llm.json", encoding="utf-8"))

    def test_replay_reproduces_the_recorded_answers(self):
        out = detect.detect(detect.group(self.items), backend="replay", recorded=self.recorded)
        self.assertEqual(len(out), 5)
        for mid, got in out.items():
            rec = self.recorded[mid]
            self.assertEqual([f["quote"] for f in got["flags"]], [f["quote"] for f in rec["flags"]], mid)
            self.assertEqual(len(got["dropped"]), len(rec.get("dropped", [])), mid)
            for f in got["flags"]:  # every kept quote is really in the cited item
                text = next(i["text"] for i in self.items if i["id"] == f["item_id"])
                self.assertIn(detect._norm(f["quote"].rstrip(".…")), detect._norm(text))

    def test_replay_drops_a_recorded_quote_that_isnt_in_the_text(self):
        mid = "M12300"
        items = [dict(i, text="(edited away)") if i["merchant_id"] == mid else i for i in self.items]
        out = detect.detect(detect.group(items), backend="replay", recorded=self.recorded)
        self.assertEqual(out[mid]["flags"], [])

    def test_cli_runs_from_the_file(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            for backend in ("rules", "replay"):
                path = os.path.join(tmp, backend + ".json")
                detect.main(["--items", self.path, "--backend", backend, "--today", "2026-11-11", "--out", path])
                self.assertEqual(len(json.load(open(path))), 5)
