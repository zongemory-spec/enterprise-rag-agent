import json
from unittest.mock import patch
import unittest
import httpx
from rag_app.embedding import HTTPEmbedding
from rag_app.generation import HTTPQuoteGenerator
from rag_app.planner import HTTPPlanner
from rag_app.security import AccessError

class AdapterTests(unittest.TestCase):
    def mock_client(self,module,handler):
        original=httpx.Client
        return patch(module+".httpx.Client",side_effect=lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    def test_embedding_index_order(self):
        with self.mock_client("rag_app.embedding",lambda r:httpx.Response(200,json={"data":[{"index":1,"embedding":[0,1]},{"index":0,"embedding":[1,0]}]})):
            self.assertEqual(HTTPEmbedding("https://invalid","fake","fake",2).embed(["a","b"]),[[1,0],[0,1]])
    def test_embedding_dimension_nan_and_zero_rejected(self):
        for vector in ([1],[0,0],["bad",1]):
            with self.mock_client("rag_app.embedding",lambda r:httpx.Response(200,json={"data":[{"index":0,"embedding":vector}]})):
                with self.assertRaises(RuntimeError):HTTPEmbedding("https://invalid","fake","fake",2).embed(["a"])
    def test_embedding_timeout_details_withheld(self):
        def fail(r):raise httpx.ReadTimeout("secret=private",request=r)
        with self.mock_client("rag_app.embedding",fail):
            with self.assertRaises(RuntimeError) as e:HTTPEmbedding("https://invalid","fake","fake",2).embed(["a"])
            self.assertNotIn("private",str(e.exception))
    def test_generation_rate_limit(self):
        with self.mock_client("rag_app.generation",lambda r:httpx.Response(429,json={"error":"private"})):
            with self.assertRaises(AccessError) as e:HTTPQuoteGenerator("https://invalid","fake","fake").generate("q",[])
            self.assertEqual(e.exception.status,503)
    def test_generation_timeout(self):
        def fail(r):raise httpx.ReadTimeout("private",request=r)
        with self.mock_client("rag_app.generation",fail):
            with self.assertRaises(AccessError) as e:HTTPQuoteGenerator("https://invalid","fake","fake").generate("q",[])
            self.assertEqual(e.exception.status,504)
    def test_planner_no_identity_or_key_in_message_body(self):
        def inspect(r):
            payload=json.loads(r.content)
            self.assertNotIn("credential-do-not-send",json.dumps(payload))
            return httpx.Response(200,json={"choices":[{"message":{"content":'{"name":"search_knowledge","arguments":{"query":"x"}}'}}]})
        with self.mock_client("rag_app.planner",inspect):
            result=HTTPPlanner("https://invalid","credential-do-not-send","fake").next([{"role":"user","content":"q"}])
            self.assertEqual(result["name"],"search_knowledge")

