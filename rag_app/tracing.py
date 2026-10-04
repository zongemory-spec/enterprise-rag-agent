"""Opt-in Langfuse v4 OTLP/HTTP JSON client; exports request metadata only."""
import base64
import os
import time
from uuid import uuid4
import httpx


class LangfuseTracer:
    def __init__(self, url, public_key, secret_key):
        if not url or not public_key or not secret_key:
            raise ValueError("Langfuse URL and both keys are required")
        self.url = url.rstrip("/") + "/api/public/otel/v1/traces"
        self.auth = "Basic " + base64.b64encode((public_key+":"+secret_key).encode()).decode()
        self.last_status = "not_sent"

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
