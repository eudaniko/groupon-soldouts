import tempfile
import unittest
from pathlib import Path

from routing.plan import load_config
from routing.suppressions import load_suppressions


class ConfigTest(unittest.TestCase):
    def test_suppress_switch_is_off_by_default(self):
        self.assertIs(load_config()["suppress_soldout_tasks"], False)

    def test_shipped_suppression_file_is_empty(self):
        self.assertEqual(load_suppressions(), [])

    def test_missing_suppression_file_means_nothing_suppressed(self):
        self.assertEqual(load_suppressions("does/not/exist.csv"), [])

    def test_suppression_row_needs_an_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            p.write_text("deal_id,merchant_id,reason,source,added_on\n,,no id,ops,2026-11-01\n")
            with self.assertRaises(ValueError):
                load_suppressions(p)


if __name__ == "__main__":
    unittest.main()
