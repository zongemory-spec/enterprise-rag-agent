"""Scoped, leased workflow checkpoints. Never an authority for document access."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from rag_app.security import AccessError


class Checkpointer:
    def __init__(self, path="data/checkpoints.sqlite3", pg_store=None):
        self.pg = pg_store
        self.path = Path(path)
        if not self.pg:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                tenant TEXT NOT NULL, actor TEXT NOT NULL, workflow TEXT NOT NULL,
                state TEXT NOT NULL, lease TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL,
                PRIMARY KEY(tenant,actor,workflow))""")

    @contextmanager
    def connect(self):
        if self.pg:
            with self.pg.connect() as c:
                yield c
        else:
            c = sqlite3.connect(self.path, timeout=10)
            c.row_factory = sqlite3.Row
            try:
                with c:
                    c.execute("BEGIN IMMEDIATE")
                    yield c
            finally:
                c.close()

    def execute(self, c, query, args):
        return c.execute(query.replace("?", "%s") if self.pg else query, args)

    def acquire(self, actor, workflow, initial):
        scope = (actor.tenant_id, actor.user_id, workflow)
        lease = uuid4().hex
        now = time.time()
        with self.connect() as c:
            self.execute(c, "INSERT INTO workflow_checkpoints VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                         (*scope, json.dumps(initial), "", 0))
            updated = self.execute(c, "UPDATE workflow_checkpoints SET lease=?,expires=? WHERE tenant=? AND actor=? AND workflow=? AND expires<=?",
                                   (lease, now + 300, *scope, now))
            if updated.rowcount != 1:
                raise AccessError("workflow_busy", 409)
            row = self.execute(c, "SELECT * FROM workflow_checkpoints WHERE tenant=? AND actor=? AND workflow=?", scope).fetchone()
            return json.loads(row["state"]), lease

    def save(self, actor, workflow, lease, state, release=False):
        with self.connect() as c:
            updated = self.execute(c, "UPDATE workflow_checkpoints SET state=?,expires=? WHERE tenant=? AND actor=? AND workflow=? AND lease=? AND expires>?",
                                   (json.dumps(state), 0 if release else time.time()+300,
                                    actor.tenant_id, actor.user_id, workflow, lease, time.time()))
            if updated.rowcount != 1:
                raise AccessError("workflow_lease_lost", 409)
