import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import server_dashboard as sd


class TestParseLimit(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sd._parse_limit("25"), 25)

    def test_clamps_high(self):
        self.assertEqual(sd._parse_limit("9999"), 100)

    def test_clamps_low(self):
        self.assertEqual(sd._parse_limit("0"), 1)

    def test_bad_input_falls_back_without_reflecting(self):
        # The XSS payload must NOT appear anywhere in the result
        self.assertEqual(sd._parse_limit("<script>alert(1)</script>"), 10)

    def test_none_falls_back(self):
        self.assertEqual(sd._parse_limit(None), 10)


if __name__ == "__main__":
    unittest.main()
