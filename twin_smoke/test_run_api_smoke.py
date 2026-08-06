#!/usr/bin/env python3

import unittest

from run_api_smoke import output_text, response_url


class ResponsesApiHelpersTests(unittest.TestCase):
    def test_response_url(self):
        self.assertEqual("https://example.test/v1/responses", response_url("https://example.test/v1/"))

    def test_output_text(self):
        payload = {
            "output": [
                {"content": [{"type": "output_text", "text": "first"}]},
                {"content": [{"type": "output_text", "text": " second"}]},
            ]
        }
        self.assertEqual("first second", output_text(payload))


if __name__ == "__main__":
    unittest.main()
