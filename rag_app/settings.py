import json,os
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
def configure_runtime(real=False,semantic=False):
    path=ROOT/"data/local_config.json"
    cfg=json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if cfg.get("postgres_config"):
        db=json.loads(Path(cfg["postgres_config"]).read_text(encoding="utf-8-sig"))
        os.environ.update(RAG_PG_DSN=db["dsn"],RAG_PG_SCHEMA=cfg.get("postgres_schema","rag_v2"),RAG_STORE="postgresql")
    if real or semantic:
        source=os.getenv("RAG_PROVIDER_ENV_FILE") or cfg.get("provider_env_file")
        values=dotenv_values(source) if source else {}
        key=os.getenv("RAG_MODEL_KEY") or values.get("DASHSCOPE_API_KEY")
        if not key:raise RuntimeError("Configure RAG_PROVIDER_ENV_FILE or RAG_MODEL_KEY.")
        os.environ["RAG_MODEL_KEY"]=key
        os.environ.setdefault("RAG_MODEL_URL",values.get("QWEN_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        os.environ.setdefault("RAG_MODEL_NAME",values.get("QWEN_MODEL") or "qwen-plus")
        os.environ.setdefault("RAG_EMBED_KEY",key)
        os.environ.setdefault("RAG_EMBED_URL",os.environ["RAG_MODEL_URL"])
        os.environ.setdefault("RAG_EMBED_MODEL","text-embedding-v4")
        os.environ.setdefault("RAG_EMBED_DIM","1024")
        # Real chat does not imply paid embeddings. Retrieval defaults to local methods.
        if real:os.environ.update(RAG_PLANNER="real",RAG_SYNTHESIS="real")
    if semantic:
        if os.getenv('RAG_STORE')!='postgresql':raise RuntimeError('Semantic mode requires PostgreSQL configuration.')
        os.environ['RAG_EMBEDDING']='real'
        os.environ.setdefault('RAG_BUDGET_DB',str(ROOT/'data/request_budget.sqlite3'))
    return cfg
def open_store():
    if os.getenv("RAG_STORE")=="postgresql":
        from rag_app.postgres_store import PostgresStore
        return PostgresStore(os.environ["RAG_PG_DSN"],os.getenv("RAG_PG_SCHEMA","rag_v2"))
    from rag_app.store import Store
    return Store(os.getenv("RAG_DB","data/rag.sqlite3"))

