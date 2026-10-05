from collections import Counter
import json
from pathlib import Path
import unittest

class DatasetTests(unittest.TestCase):
    def test_split_inventory_and_annotations(self):
        root=Path(__file__).parents[1]
        q=json.loads((root/"data/questions.json").read_text(encoding="utf-8"))["questions"]
        self.assertEqual(len(q),60);self.assertEqual(len({(x["actor"],x["query"]) for x in q}),60)
        dev={x["query"] for x in q if x["split"]=="dev"}
        test={x["query"] for x in q if x["split"]=="test"}
        self.assertFalse(dev & test)
        self.assertEqual(Counter(x["split"] for x in q),{"dev":30,"test":30})
        for split in ("dev","test"):
            self.assertEqual(Counter(x["category"] for x in q if x["split"]==split),
                {"answerable":10,"cross_document":5,"unanswerable":5,"unauthorized":5,"injection":5})
        ids={r["document_id"] for r in json.loads((root/"data/synthetic/manifest.json").read_text(encoding="utf-8"))}
        for r in q:
            self.assertTrue(set(r["expected_doc_ids"])<=ids)
            if r["expected_refusal"]:self.assertFalse(r["reference_points"])
            else:self.assertTrue(r["reference_points"])

