"""Clone synthetic knowledge/vector tables into a new schema without API calls."""
import json
from pathlib import Path
from psycopg import sql
from rag_app.postgres_store import PostgresStore
from rag_app.pg_native_index import NativePGIndex

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    original=Path(r'D:\desktop\Enterprise RAG Agent\Enterprise RAG Agent v3_3')
    cfg=json.loads((original/'data/local_config.json').read_text(encoding='utf-8-sig'))
    database=json.loads(Path(cfg['postgres_config']).read_text(encoding='utf-8-sig'))
    schema='rag_v3_4_hybrid';store=PostgresStore(database['dsn'],schema);NativePGIndex(store)
    with store.connect() as connection:
        if connection.execute('SELECT COUNT(*) AS n FROM documents').fetchone()['n']:raise SystemExit('Target already populated; left unchanged.')
        for table in ['documents','chunks','embeddings','tickets']:
            connection.execute(sql.SQL('INSERT INTO {} SELECT * FROM {}.{}').format(sql.Identifier(table),sql.Identifier(cfg['postgres_schema']),sql.Identifier(table)))
        connection.execute(sql.SQL("UPDATE metadata SET value=(SELECT value FROM {}.metadata WHERE key='index_version') WHERE key='index_version'").format(sql.Identifier(cfg['postgres_schema'])))
    cfg['postgres_schema']=schema
    cfg['budget_db']=str(original/'data/request_budget.sqlite3')
    path=root/'data/local_config.json'
    if path.exists():raise SystemExit('Private config exists; left unchanged.')
    path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
    print('Copied synthetic knowledge and existing vectors into isolated v3.4 schema. No API calls; shared original budget.')
