#!/usr/bin/env python3

import unittest

from validate_results import deduplicate_model_items


class DeduplicateModelItemsTests(unittest.TestCase):
    def test_keeps_more_complete_duplicate(self):
        sparse = {"openreview_id": "paper-1", "research_tags": ["agent"]}
        complete = {
            "openreview_id": "paper-1",
            "research_tags": ["agent", "education"],
            "positive_factors": ["clear evidence"],
        }
        other = {"openreview_id": "paper-2", "research_tags": ["optimization"]}

        items, duplicate_ids, dropped = deduplicate_model_items([sparse, other, complete])

        self.assertEqual([complete, other], items)
        self.assertEqual(["paper-1"], duplicate_ids)
        self.assertEqual(1, dropped)

    def test_preserves_first_record_on_equal_completeness(self):
        first = {"openreview_id": "paper-1", "research_tags": ["first"]}
        second = {"openreview_id": "paper-1", "research_tags": ["other"]}

        items, duplicate_ids, dropped = deduplicate_model_items([first, second])

        self.assertEqual([first], items)
        self.assertEqual(["paper-1"], duplicate_ids)
        self.assertEqual(1, dropped)


if __name__ == "__main__":
    unittest.main()
