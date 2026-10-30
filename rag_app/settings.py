import json
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def configure_runtime(real=False, semantic=False):
    path = ROOT / 'data/local_config.json'
    cfg = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if cfg.get('postgres_config'):
        db = json.loads(Path(cfg['postgres_config']).read_text(encoding='utf-8-sig'))
        os.environ.update(RAG_PG_DSN=db['dsn'], RAG_PG_SCHEMA=cfg.get('postgres_schema', 'rag_v2'), RAG_STORE='postgresql')
    source = os.getenv('RAG_PROVIDER_ENV_FILE') or cfg.get('provider_env_file')
    values = dotenv_values(source) if source and (real or semantic) else {}
    provider_key = values.get('DASHSCOPE_API_KEY')
    if real:
        key = os.getenv('RAG_MODEL_KEY') or provider_key
        if not key:
            raise RuntimeError('Configure RAG_MODEL_KEY or RAG_PROVIDER_ENV_FILE.')
        os.environ['RAG_MODEL_KEY'] = key
        os.environ.setdefault('RAG_MODEL_URL', values.get('QWEN_BASE_URL') or 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        os.environ.setdefault('RAG_MODEL_NAME', values.get('QWEN_MODEL') or 'qwen-plus')
        os.environ['RAG_PLANNER'] = 'langchain'
        os.environ['RAG_SYNTHESIS'] = 'real'
    if semantic:
        if os.getenv('RAG_STORE') != 'postgresql':
            raise RuntimeError('Semantic mode requires RAG_STORE=postgresql and RAG_PG_DSN.')
        key = os.getenv('RAG_EMBED_KEY') or os.getenv('RAG_MODEL_KEY') or provider_key
        if not key:
            raise RuntimeError('Configure RAG_EMBED_KEY before enabling semantic requests.')
        os.environ['RAG_EMBED_KEY'] = key
        os.environ.setdefault('RAG_EMBED_URL', os.getenv('RAG_MODEL_URL') or values.get('QWEN_BASE_URL') or 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        os.environ.setdefault('RAG_EMBED_MODEL', 'text-embedding-v4')
        os.environ.setdefault('RAG_EMBED_DIM', '1024')
        os.environ['RAG_EMBEDDING'] = 'real'
        os.environ.setdefault('RAG_BUDGET_DB', cfg.get('budget_db') or str(ROOT / 'data/request_budget.sqlite3'))
    return cfg


def open_store():
    if os.getenv('RAG_STORE') == 'postgresql':
        from rag_app.postgres_store import PostgresStore
        return PostgresStore(os.environ['RAG_PG_DSN'], os.getenv('RAG_PG_SCHEMA', 'rag_v2'))
    from rag_app.store import Store
    return Store(os.getenv('RAG_DB', 'data/rag.sqlite3'))
