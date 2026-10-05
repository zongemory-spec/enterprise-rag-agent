"""Persistent local attempt budgets. Failed requests consume budget too."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from rag_app.security import AccessError

class PersistentBudget:
    def __init__(self,path,limits=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.limits=limits or {'embedding':12,'chat':4}
        with self.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS attempts(kind TEXT PRIMARY KEY,used INTEGER NOT NULL)')
    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=10)
        try:
            with connection:yield connection
        finally:connection.close()
    def __call__(self,kind):
        if kind not in self.limits:raise AccessError('unknown_budget_kind',429)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO attempts VALUES (?,0) ON CONFLICT DO NOTHING',(kind,))
            used=c.execute('SELECT used FROM attempts WHERE kind=?',(kind,)).fetchone()[0]
            if used>=self.limits[kind]:raise AccessError(kind+'_budget_exhausted',429)
            c.execute('UPDATE attempts SET used=used+1 WHERE kind=?',(kind,))
    def status(self):
        with self.connect() as c:used=dict(c.execute('SELECT kind,used FROM attempts'))
        return {kind:{'used':used.get(kind,0),'limit':limit} for kind,limit in self.limits.items()}
