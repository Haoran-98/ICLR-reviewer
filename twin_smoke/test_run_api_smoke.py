#!/usr/bin/env python3

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from run_api_smoke import load_auth, output_text, response_url


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

    def test_automation_credentials_take_precedence(self):
        with TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth"
            auth_path.write_text(
                '\n'.join(
                    [
                        'export OPENAI_BASE_URL="https://interactive.example/v1"',
                        'export OPENAI_API_KEY="interactive-key"',
                        'export OPENAI_WEAK_MODEL_ID="interactive-model"',
                        'export OPENAI_BASE_AUTOMATION_URL="https://automation.example/v1"',
                        'export OPENAI_API_AUTOMATION_KEY="automation-key"',
                        'export OPENAI_AUTOMATION_MODEL_ID="automation-model"',
                    ]
                ),
                encoding="utf-8",
            )

            auth = load_auth(auth_path)

        self.assertEqual("https://automation.example/v1", auth["OPENAI_BASE_URL"])
        self.assertEqual("automation-key", auth["OPENAI_API_KEY"])
        self.assertEqual("automation-model", auth["OPENAI_WEAK_MODEL_ID"])


if __name__ == "__main__":
    unittest.main()
