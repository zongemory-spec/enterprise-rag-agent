"""One-shot read-only SQLite -> empty PostgreSQL schema migration."""
import sqlite3,json
from contextlib import closing
from pathlib import Path
from psycopg import sql
from psycopg.types.json import Jsonb
TABLES=("documents","chunks","runs","tickets","audit")
JSON_FIELDS={"allowed_groups","chunk_ids","metadata"}
def migrate(source,target):
    source=Path(source).resolve(strict=True)
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as old:
        old.row_factory=sqlite3.Row
        old.execute("BEGIN")
        if old.execute("PRAGMA user_version").fetchone()[0]!=1:raise ValueError("Unsupported source schema")
        with target.connect() as new:
            new.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),27183)")
            new.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(sql.SQL(",").join(map(sql.Identifier,TABLES))))
            for table in TABLES:
                if new.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchone():raise ValueError("Target must be empty; choose a new schema")
            counts={}
            for table in TABLES:
                rows=old.execute('SELECT * FROM "'+table+'"').fetchall()
                for row in rows:
                    columns=list(row.keys())
                    values=[Jsonb(json.loads(row[k])) if k in JSON_FIELDS else row[k] for k in columns]
                    new.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(sql.Identifier(table),sql.SQL(",").join(map(sql.Identifier,columns)),sql.SQL(",").join(sql.Placeholder() for _ in columns)),values)
                counts[table]=len(rows)
            generation=old.execute("SELECT value FROM metadata WHERE key='index_version'").fetchone()[0]
            new.execute("UPDATE metadata SET value=%s WHERE key='index_version'",(str(generation),))
    return counts
if __name__=="__main__":
    import argparse
    from rag_app.settings import configure_runtime,open_store
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    args=parser.parse_args()
    configure_runtime()
    target=open_store()
    if target.backend!="postgresql":raise SystemExit("PostgreSQL configuration required")
    print(json.dumps(migrate(args.source,target)))
