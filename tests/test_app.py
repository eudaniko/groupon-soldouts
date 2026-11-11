import unittest

from soldouts.app import parse_rate


class ParseRateTest(unittest.TestCase):
    def test_number(self):
        self.assertEqual(parse_rate("25"), 25.0)
        self.assertEqual(parse_rate("12.5"), 12.5)

    def test_clamped(self):
        self.assertEqual(parse_rate("-3"), 0.0)
        self.assertEqual(parse_rate("9999"), 500.0)

    def test_junk_means_default(self):
        for text in (None, "", "abc", "nan", "NaN", "inf", "-inf"):
            self.assertIsNone(parse_rate(text), text)


if __name__ == "__main__":
    unittest.main()
