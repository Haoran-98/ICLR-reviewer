#!/usr/bin/env python3

import json
import unittest
from collections import Counter

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


if __name__ == "__main__":
    unittest.main()
