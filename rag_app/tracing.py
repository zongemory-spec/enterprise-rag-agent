"""Opt-in Langfuse ingestion client. Never exports prompts, documents or credentials."""
import base64
from datetime import datetime, timezone
import os
import time
from uuid import uuid4
import httpx


class LangfuseTracer:
    def __init__(self, url, public_key, secret_key):
        if not url or not public_key or not secret_key:
            raise ValueError("Langfuse URL and both keys are required")
        self.url = url.rstrip("/") + "/api/public/ingestion"
        self.auth = "Basic " + base64.b64encode((public_key+":"+secret_key).encode()).decode()
        self.last_status = "not_sent"

    def record(self, operation, elapsed_ms, status):
        stamp = datetime.now(timezone.utc).isoformat()
        event = {"id": uuid4().hex, "type": "trace-create", "timestamp": stamp,
                 "body": {"id": uuid4().hex, "name": operation, "timestamp": stamp,
                          "metadata": {"duration_ms": round(elapsed_ms, 3), "status": status}}}
        try:
            response = httpx.post(self.url, headers={"Authorization": self.auth},
                                  json={"batch": [event]}, timeout=3)
            response.raise_for_status()
            body = response.json()
            self.last_status = "rejected" if body.get("errors") else "accepted"
        except (httpx.HTTPError, ValueError, AttributeError):
            self.last_status = "unavailable"


def configured_tracer():
    if os.getenv("RAG_TRACING", "off") == "off":
        return None
    if os.getenv("RAG_TRACING") != "langfuse":
        raise ValueError("RAG_TRACING must be off or langfuse")
    return LangfuseTracer(os.getenv("LANGFUSE_BASE_URL"), os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY"))
