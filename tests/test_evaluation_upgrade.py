import json
from pathlib import Path
import tempfile
import unittest

from evaluate import evaluate
from init_demo import populate
from package_source import build_archive
from rag_app.service import Service
from rag_app.store import Store
from rag_app.reranking import apply_scores


class EvaluationUpgradeTests(unittest.TestCase):
    def test_before_after_rerank_metrics_use_actual_order(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'db')
            populate(store)
            question = {'question_id': 'fixture', 'actor': 'alice', 'query': '差旅报销 入职材料',
                        'category': 'answerable', 'expected_doc_ids': ['S002'],
                        'expected_refusal': False, 'reference_points': ['入职材料']}
            class Reranker:
                model_id = 'controlled-test-fixture'
                def rerank(self, query, rows, top_k):
                    return apply_scores(rows, [1. if r['document_id'] == 'S002' else 0. for r in rows], top_k)
            result = evaluate(store, [question], 'bm25', Service(store, reranker=Reranker()), True)
            self.assertEqual(result['rows'][0]['ordered_retrieved_doc_ids'][0], 'S002')
            self.assertEqual(result['metrics']['recall_at_1_macro'], 1.)
            self.assertEqual(result['metrics']['reranker'], 'controlled-test-fixture')

    def test_source_archive_contains_manifest_but_excludes_runtime_files(self):
        import hashlib
        import zipfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'source'
            root.mkdir()
            (root / 'data/synthetic').mkdir(parents=True)
            (root / 'data/questions.json').write_text('{}')
            (root / 'main.py').write_text('print(1)')
            (root / '.env').write_text('PRIVATE=do-not-package')
            (root / '.env.example').write_text('KEY=replace_me')
            (root / 'data/demo_auth.json').write_text('private-token')
            (root / 'data/runtime.sqlite3').write_text('private-data')
            (root / '.venv').mkdir()
            (root / '.venv/private.py').write_text('private-environment')
            out = Path(temp) / 'source.zip'
            build_archive(root, out)
            with zipfile.ZipFile(out) as archive:
                self.assertIsNone(archive.testzip())
                names = archive.namelist()
                self.assertFalse(any(n.endswith('/.env') or 'demo_auth' in n or '.sqlite3' in n or '.venv' in n for n in names))
                manifest = json.loads(archive.read('enterprise-rag-agent-v4.2/PACKAGE_MANIFEST.json'))
                for entry in manifest['files']:
                    content = archive.read(manifest['root'] + '/' + entry['path'])
                    self.assertEqual(hashlib.sha256(content).hexdigest(), entry['sha256'])
            with self.assertRaises(FileExistsError): build_archive(root, out)
