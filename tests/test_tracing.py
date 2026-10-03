import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import unittest
from unittest.mock import patch
import httpx
from rag_app.tracing import LangfuseTracer,configured_tracer


class TracingTests(unittest.TestCase):
    def test_actual_http_transport_and_minimal_payload(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length']))),self.headers.get('x-langfuse-ingestion-version')))
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(b'{}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            tracer=LangfuseTracer('http://127.0.0.1:'+str(server.server_port),'test-public','test-secret')
            tracer.record('/agent',10,200)
            self.assertEqual(tracer.last_status,'accepted')
            self.assertEqual(received[0][0],'/api/public/otel/v1/traces')
            self.assertEqual(received[0][2],'4')
            span=received[0][1]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
            self.assertEqual(span['name'],'/agent')
            self.assertEqual(len(span['traceId']),32)
            self.assertEqual(len(span['spanId']),16)
            self.assertEqual(int(span['endTimeUnixNano'])-int(span['startTimeUnixNano']),10_000_000)
            self.assertEqual({a['key'] for a in span['attributes']},{'langfuse.observation.type','langfuse.observation.metadata.duration_ms','langfuse.observation.metadata.status'})
            self.assertNotIn('test-secret',json.dumps(received))
        finally:server.shutdown();server.server_close();worker.join()

    def test_failure_does_not_break_business_request(self):
        tracer=LangfuseTracer('https://example.invalid','test-public','test-secret')
        with patch('rag_app.tracing.httpx.post',side_effect=httpx.ConnectError('private upstream details')):
            tracer.record('/ask',1,200)
        self.assertEqual(tracer.last_status,'unavailable')

    def test_partial_batch_rejection_and_missing_credentials(self):
        tracer=LangfuseTracer('https://example.invalid','test-public','test-secret')
        response=httpx.Response(200,json={'partialSuccess':{'rejectedSpans':'1'}},request=httpx.Request('POST','https://example.invalid'))
        with patch('rag_app.tracing.httpx.post',return_value=response):tracer.record('/ask',1,200)
        self.assertEqual(tracer.last_status,'rejected')
        with patch.dict('os.environ',{'RAG_TRACING':'langfuse','LANGFUSE_BASE_URL':'','LANGFUSE_PUBLIC_KEY':'','LANGFUSE_SECRET_KEY':''}):
            with self.assertRaises(ValueError):configured_tracer()
