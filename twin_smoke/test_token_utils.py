#!/usr/bin/env python3

import unittest

from token_utils import Utf8HeuristicEncoder


class Utf8HeuristicEncoderTests(unittest.TestCase):
    def test_counts_english_conservatively(self):
        encoder = Utf8HeuristicEncoder()
        self.assertEqual(4, len(encoder.encode_ordinary("hello world")))

    def test_counts_cjk_by_utf8_width(self):
        encoder = Utf8HeuristicEncoder()
        self.assertEqual(4, len(encoder.encode_ordinary("认知引导")))


if __name__ == "__main__":
    unittest.main()
