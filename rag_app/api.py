import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI,Depends,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse,JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from rag_app.security import Registry,AccessError
from rag_app.store import Store
from rag_app.service import Service

class Question(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    query:str=Field(min_length=1,max_length=2000)
    method:Literal["keyword","hash-vector","pgvector","hybrid"]="keyword"
    top_k:int=Field(default=4,ge=1,le=8)

class AgentQuestion(Question):
    workflow_id:str | None=Field(default=None,min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$")

def create_app(store=None,auth=None,generator=None,pg_index=None,planner=None,synthesizer=None):
    from rag_app.settings import open_store
    store=store or open_store()
    auth=auth or Registry.from_file(os.getenv("RAG_AUTH_FILE","data/demo_auth.json"))
    from rag_app.synthesis import ModelBudget,HTTPAnswerSynthesizer
    budget=ModelBudget(int(os.getenv("RAG_CHAT_LIMIT","9")))
    from rag_app.request_budget import PersistentBudget
    persistent_budget=PersistentBudget(os.environ['RAG_BUDGET_DB']) if os.getenv('RAG_BUDGET_DB') else None
    chat_guard=persistent_budget or budget
    if os.getenv("RAG_GENERATOR","extractive")=="real" and generator is None:
        from rag_app.generation import HTTPQuoteGenerator
        generator=HTTPQuoteGenerator(os.environ["RAG_MODEL_URL"],os.environ["RAG_MODEL_KEY"],os.environ["RAG_MODEL_NAME"])
    if os.getenv("RAG_PLANNER","offline")=="real" and planner is None:
        from rag_app.planner import HTTPPlanner
        planner=HTTPPlanner(os.environ["RAG_MODEL_URL"],os.environ["RAG_MODEL_KEY"],os.environ["RAG_MODEL_NAME"],chat_guard)
    if os.getenv("RAG_SYNTHESIS")=="real" and synthesizer is None:
        synthesizer=HTTPAnswerSynthesizer(os.environ["RAG_MODEL_URL"],os.environ["RAG_MODEL_KEY"],os.environ["RAG_MODEL_NAME"],chat_guard)
    if os.getenv("RAG_PG_DSN") and pg_index is None:
        from rag_app.pg_index import PGIndex
        embedder=None
        if os.getenv("RAG_EMBEDDING","hash")=="real":
            from rag_app.embedding import HTTPEmbedding
            if persistent_budget is None:raise RuntimeError('Real embeddings require RAG_BUDGET_DB.')
            embedder=HTTPEmbedding(os.environ["RAG_EMBED_URL"],os.environ["RAG_EMBED_KEY"],os.environ["RAG_EMBED_MODEL"],int(os.environ["RAG_EMBED_DIM"]),persistent_budget)
        if getattr(store,"backend","sqlite")=="postgresql":
            from rag_app.pg_native_index import NativePGIndex
            pg_index=NativePGIndex(store,embedder)
        else:
            pg_index=PGIndex(os.environ["RAG_PG_DSN"],embedder)
    service=Service(store,generator,pg_index)
    from rag_app.checkpoint import Checkpointer
    from rag_app.tracing import configured_tracer
    checkpoints=Checkpointer(os.getenv("RAG_CHECKPOINT_DB","data/checkpoints.sqlite3"),
                             store if getattr(store,"backend",None)=="postgresql" else None)
    tracer=configured_tracer()
    app=FastAPI(title="企业知识问答原型")
    audit_logger=logging.getLogger("rag.audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate=False
    if not audit_logger.handlers:
        handler=logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        audit_logger.addHandler(handler)
    app.state.service=service
    app.state.tracer=tracer

    @app.middleware("http")
    async def audit(request,call_next):
        start=time.perf_counter()
        request.state.request_id=uuid4().hex
        request.state.reason="completed"
        try:r=await call_next(request)
        except Exception:
            request.state.reason="internal_error";r=JSONResponse({"detail":"internal_error"},status_code=500)
        store.audit(request.state.request_id,r.status_code,request.state.reason)
        audit_logger.info(json.dumps({"request_id":request.state.request_id,"status":r.status_code,"reason":request.state.reason}))
        r.headers["X-Request-ID"]=request.state.request_id
        if tracer:
            # Use route templates: arbitrary user paths and parameters are not exported.
            route=getattr(request.scope.get("route"),"path","unmatched")
            import asyncio
            await asyncio.to_thread(tracer.record,route,(time.perf_counter()-start)*1000,r.status_code)
        return r

    @app.exception_handler(AccessError)
    async def access(request,exc):
        request.state.reason=exc.reason
        return JSONResponse({"detail":exc.reason},status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        request.state.reason="invalid_request"
        return JSONResponse({"detail":"invalid_request"},status_code=422)

    def authenticated(request:Request):
        return auth.authenticate(request.headers.get("Authorization"))

    @app.get("/health")
    def health():return {"status":"ok"}

    @app.get("/capabilities")
    def capabilities():return {"planner":"real" if planner else "offline-script","synthesis":getattr(synthesizer,"model","offline-extractive"),"chat_attempt_limit":budget.limit,"chat_attempts_used":budget.used,"tool_call_limit":3,'vector_index':pg_index.status() if hasattr(pg_index,'status') else None,'persistent_budget':persistent_budget.status() if persistent_budget else None}

    @app.get("/",response_class=HTMLResponse)
    def ui():return Path(__file__).with_name("ui.html").read_text(encoding="utf-8-sig")

    @app.post("/ask")
    def ask(body:Question,ctx=Depends(authenticated)):
        return service.ask(body.query,ctx,body.method,body.top_k)

    @app.post("/agent")
    def agent(body:AgentQuestion,ctx=Depends(authenticated)):
        from rag_app.workflow import execute
        return execute(service,checkpoints,body.query,ctx,planner,body.method,body.workflow_id,synthesizer)

    @app.get("/citations/{chunk_id}")
    def citation(chunk_id:str,ctx=Depends(authenticated)):
        row=store.citation(chunk_id,ctx)
        return {k:row[k] for k in ("chunk_id","document_id","version","title","location","source","text")}

    @app.get("/runs/{run_id}")
    def run(run_id:str,ctx=Depends(authenticated)):
        return store.run(run_id,ctx)
    return app

