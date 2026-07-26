#!/usr/bin/env python3

import json
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

import manage


class AutomationTests(unittest.TestCase):
    def test_allocation_and_rendering(self):
        records = [
            {"year": 2024, "openreview_id": f"a{i}"} for i in range(4)
        ] + [
            {"year": 2025, "openreview_id": f"b{i}"} for i in range(6)
        ]
        selected = manage.allocate(records, 5)
        self.assertEqual(len(selected), 5)
        self.assertEqual({2024: 2, 2025: 3}, dict(Counter(item["year"] for item in selected)))

        registry = json.loads((manage.REPO / "agents/reviewer_groups.json").read_text(encoding="utf-8"))
        registered = {agent_id for ids in registry["groups"].values() for agent_id in ids}
        self.assertEqual(registered, set(registry["agents"]))
        groups, recent = manage.render_agents(registry, chinese=False)
        self.assertIn("iclr_reviewer_orchestrator", groups)
        self.assertIn("iclr_reviewer_orchestrator", recent)

        rendered = manage.replace_block("before\n<!-- X:START -->\nold\n<!-- X:END -->\nafter", "X", "new")
        self.assertIn("<!-- X:START -->\nnew\n<!-- X:END -->", rendered)

        for filename in ("README.md", "README.zh-CN.md"):
            readme = (manage.REPO / filename).read_text(encoding="utf-8")
            self.assertIn("<!-- DAILY_ACTIVITY:START -->", readme)
            self.assertIn("<!-- WEEKLY_ACTIVITY:START -->", readme)
            self.assertIn("<!-- AGENT_GROUPS:START -->", readme)
            self.assertIn("<!-- RECENT_AGENTS:START -->", readme)
            self.assertNotIn("AUTOMATION_PROGRESS", readme)

    def test_public_activity_contains_only_publishable_paper_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper_path = root / "paper.json"
            paper_path.write_text(json.dumps({
                "title": "A Paper | With a Pipe",
                "primary_area": "education",
                "openreview_url": "https://openreview.net/forum?id=test-paper",
            }), encoding="utf-8")
            run_dir = root / "daily" / "2026-07-26"
            run_dir.mkdir(parents=True)
            (run_dir / "SUCCESS.json").write_text(json.dumps({"date": "2026-07-26"}), encoding="utf-8")
            (run_dir / "manifest.jsonl").write_text(json.dumps({
                "path": str(paper_path), "openreview_id": "test-paper", "year": 2026,
            }) + "\n", encoding="utf-8")
            (run_dir / "normalized_results.json").write_text(json.dumps({"papers": [{
                "openreview_id": "test-paper",
                "research_tags": ["agent", "education", "evaluation", "unused"],
                "response_outcomes": [{"reviewer_id": "must-not-leak"}],
            }]}), encoding="utf-8")

            activity = manage.build_activity(root, date(2026, 7, 26))
            public_paper = activity["recent_days"][0]["papers"][0]
            self.assertEqual(["agent", "education", "evaluation"], public_paper["research_tags"])
            self.assertNotIn("path", public_paper)
            self.assertNotIn("response_outcomes", public_paper)
            rendered = manage.render_daily_activity(activity, chinese=False)
            self.assertIn("A Paper \\| With a Pipe", rendered)
            self.assertNotIn("must-not-leak", json.dumps(activity))


if __name__ == "__main__":
    unittest.main()
