"""Opt-in Langfuse v4 OTLP/HTTP JSON client; exports request metadata only."""
import base64
import os
import time
from uuid import uuid4
import httpx
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading

_active = ContextVar('rag_trace', default=None)
_parent = ContextVar('rag_parent_span', default=None)


@dataclass
class TraceBatch:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    spans: list = field(default_factory=list)
    lock: object = field(default_factory=threading.Lock)


@contextmanager
def trace_scope(enabled=True):
    batch = TraceBatch() if enabled else None
    token = _active.set(batch)
    try:
        yield batch
    finally:
        _active.reset(token)


@contextmanager
def span(name):
    """Collect nested metadata-only spans. Never serialize questions or documents."""
    batch = _active.get()
    metadata = {}
    if batch is None:
        yield metadata
        return
    start = time.time_ns()
    parent_id = _parent.get()
    span_id = uuid4().hex[:16]
    token = _parent.set(span_id)
    status = 1
    try:
        yield metadata
    except BaseException:
        status = 2
        raise
    finally:
        _parent.reset(token)
        end = time.time_ns()
        attrs = [{'key': 'langfuse.observation.type', 'value': {'stringValue': 'span'}},
                 {'key': 'langfuse.observation.metadata.duration_ms', 'value': {'doubleValue': (end-start)/1e6}}]
        # Explicit allowlist prevents accidental export of arbitrary model/tool data.
        for key in ('candidate_count', 'selected_count', 'model', 'input_tokens', 'output_tokens', 'status'):
            value = metadata.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                kind = 'stringValue' if isinstance(value, str) else 'intValue' if isinstance(value, int) else 'doubleValue'
                attrs.append({'key': 'langfuse.observation.metadata.' + key,
                              'value': {kind: str(value) if kind == 'intValue' else value}})
        item = {'traceId': batch.trace_id, 'spanId': span_id, 'name': name, 'kind': 1,
                'startTimeUnixNano': str(start), 'endTimeUnixNano': str(end),
                'status': {'code': 2 if metadata.get('status', 0) >= 500 else status}, 'attributes': attrs}
        if parent_id:
            item['parentSpanId'] = parent_id
        with batch.lock:
            batch.spans.append(item)


class LangfuseTracer:
    def __init__(self, url, public_key, secret_key):
        if not url or not public_key or not secret_key:
            raise ValueError("Langfuse URL and both keys are required")
        self.url = url.rstrip("/") + "/api/public/otel/v1/traces"
        self.auth = "Basic " + base64.b64encode((public_key+":"+secret_key).encode()).decode()
        self.last_status = "not_sent"

    def export(self, batch):
        if batch is None or not batch.spans:
            return
        payload = {'resourceSpans': [{'resource': {'attributes': [
            {'key': 'service.name', 'value': {'stringValue': 'enterprise-rag'}}]},
            'scopeSpans': [{'scope': {'name': 'rag.pipeline', 'version': '4.0'}, 'spans': batch.spans}]}]}
        try:
            response = httpx.post(self.url, headers={'Authorization': self.auth,
                'x-langfuse-ingestion-version': '4'}, json=payload, timeout=3)
            response.raise_for_status()
            rejected = (response.json().get('partialSuccess') or {}).get('rejectedSpans', 0)
            self.last_status = 'rejected' if int(rejected) else 'accepted'
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            self.last_status = 'unavailable'

    def record(self, operation, elapsed_ms, status):
        end = time.time_ns()
        span = {"traceId": uuid4().hex, "spanId": uuid4().hex[:16],
                "name": operation, "kind": 2,
                "startTimeUnixNano": str(end - max(0, int(elapsed_ms * 1_000_000))),
                "endTimeUnixNano": str(end),
                "status": {"code": 2 if status >= 500 else 1},
                "attributes": [
                    {"key": "langfuse.observation.type", "value": {"stringValue": "span"}},
                    {"key": "langfuse.observation.metadata.duration_ms", "value": {"doubleValue": round(elapsed_ms, 3)}},
                    {"key": "langfuse.observation.metadata.status", "value": {"intValue": str(status)}}]}
        payload = {"resourceSpans": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "enterprise-rag"}}]},
            "scopeSpans": [{"scope": {"name": "rag.request", "version": "3.1"}, "spans": [span]}]}]}
        try:
            response = httpx.post(self.url, headers={"Authorization": self.auth,
                                  "x-langfuse-ingestion-version": "4"}, json=payload, timeout=3)
            response.raise_for_status()
            body = response.json()
            partial = body.get("partialSuccess") or {}
            self.last_status = "rejected" if int(partial.get("rejectedSpans", 0)) else "accepted"
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            self.last_status = "unavailable"


def configured_tracer():
    if os.getenv("RAG_TRACING", "off") == "off":
        return None
    if os.getenv("RAG_TRACING") != "langfuse":
        raise ValueError("RAG_TRACING must be off or langfuse")
    return LangfuseTracer(os.getenv("LANGFUSE_BASE_URL"), os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY"))
