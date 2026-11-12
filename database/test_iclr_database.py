from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import iclr_database as db


class DatabaseHelpersTest(unittest.TestCase):
    def test_area_aliases_and_numbers(self) -> None:
        self.assertEqual(db.canonical_area("Infrastructure, software libraries, hardware, etc."), "infrastructure_systems")
        self.assertEqual(db.number("8: accept"), 8.0)
        self.assertIsNone(db.number(None))
        self.assertEqual(db.json_safe({"text": "a\x00b"}), {"text": "a\ufffdb"})
        self.assertEqual(db.unwrap_openreview_content({"rating": {"value": "8"}}), {"rating": "8"})
        self.assertEqual(db.TOKEN_EXPIRES_SECONDS, 604800)
        self.assertEqual(db.TOKEN_REFRESH_SECONDS, 601200)
        payload = db.base64.urlsafe_b64encode(json.dumps({"iat": 100, "exp": 604900}).encode()).decode().rstrip("=")
        token = f"e30.{payload}.sig"
        self.assertFalse(db.token_refresh_due(token, now=100 + db.TOKEN_REFRESH_SECONDS - 1))
        self.assertTrue(db.token_refresh_due(token, now=100 + db.TOKEN_REFRESH_SECONDS))

    def test_inventory_excludes_workshops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            state = root / "state"
            for year in db.YEARS:
                (source / str(year)).mkdir(parents=True)
                (source / ".raw_openreview" / str(year)).mkdir(parents=True)
                (source / "fulltext" / "pdf" / str(year)).mkdir(parents=True)
                (source / "fulltext" / "markdown" / str(year)).mkdir(parents=True)
            main = {"openreview_id": "main1", "track": "main", "title": "Main"}
            workshop = {"openreview_id": "workshop1", "track": "workshop", "title": "Workshop"}
            (source / "2024" / "main1.json").write_text(json.dumps(main), encoding="utf-8")
            (source / "2024" / "workshop1.json").write_text(json.dumps(workshop), encoding="utf-8")
            args = Namespace(source=source, state=state, hash_workers=1)
            summary = db.inventory(args)
            self.assertEqual(summary["main_papers"], 1)
            self.assertEqual(summary["excluded_records"], 1)

    def test_text_first_index_only_routes_deep_content(self) -> None:
        text = """# Abstract
We introduce a framework overview and outperform the baseline.

Figure 1: System overview.
Table 2: Main results.
Theorem 1: The estimator is consistent.
See Equation (3) and the ablation study.

---

## Experiments
More evidence follows.
"""
        result = db.lightweight_fulltext_index(text)
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["object_counts"], {
            "figure": 1,
            "table": 1,
            "theorem": 1,
            "equation": 1,
        })
        self.assertTrue(result["routing_signals"]["result_table_sensitive"])
        self.assertTrue(result["routing_signals"]["ablation_sensitive"])
        self.assertFalse(result["routing_signals"]["deep_parse_requested"])
        self.assertTrue(all(item["confidence"] <= 0.95 for item in result["objects"]))


if __name__ == "__main__":
    unittest.main()
