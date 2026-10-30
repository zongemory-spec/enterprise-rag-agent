"""Shared SQLite/PostgreSQL storage for conversations, feedback and index jobs."""
import json
from datetime import datetime, timezone
from uuid import uuid4
from rag_app.security import AccessError

SCHEMA = [
    'CREATE TABLE IF NOT EXISTS app_conversations(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,actor TEXT NOT NULL,version INTEGER NOT NULL,created TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS app_turns(id TEXT PRIMARY KEY,conversation TEXT NOT NULL,position INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(conversation,position))',
    'CREATE TABLE IF NOT EXISTS app_answers(run_id TEXT PRIMARY KEY,tenant TEXT NOT NULL,actor TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS app_feedback(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,tenant TEXT NOT NULL,actor TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(run_id,tenant,actor))',
    'CREATE TABLE IF NOT EXISTS app_jobs(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,actor TEXT NOT NULL,document_id TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL)',
]


def now():
    return datetime.now(timezone.utc).isoformat()


class ApplicationState:
    def __init__(self, store):
        self.store = store
        with store.connect() as c:
            for statement in SCHEMA:
                c.execute(statement)

    def sql(self, c, query, args=()):
        return c.execute(query.replace('?', '%s') if self.store.backend == 'postgresql' else query, args)

    def conversation(self, actor, conversation_id):
        with self.store.connect() as c:
            row = self.sql(c, 'SELECT * FROM app_conversations WHERE id=? AND tenant=? AND actor=?',
                           (conversation_id, actor.tenant_id, actor.user_id)).fetchone()
        if row is None:
            raise AccessError('conversation_not_found', 404)
        return dict(row)

    def create_conversation(self, actor):
        cid = uuid4().hex
        with self.store.connect() as c:
            self.sql(c, 'INSERT INTO app_conversations VALUES (?,?,?,?,?)', (cid, actor.tenant_id, actor.user_id, 0, now()))
        return {'conversation_id': cid, 'version': 0}

    def conversations(self, actor):
        with self.store.connect() as c:
            rows = self.sql(c, 'SELECT id,version,created FROM app_conversations WHERE tenant=? AND actor=? ORDER BY created DESC LIMIT 100',
                            (actor.tenant_id, actor.user_id)).fetchall()
        return [dict(r) for r in rows]

    def visible_answer(self, actor, payload):
        trace=payload.get('retrieval_trace') or {}
        ids=set(payload.get('context_chunk_ids', []))|set(payload.get('retrieved_chunk_ids', []))|set(payload.get('clarification_source_ids',[]))
        for attempt in (trace.get('correction') or {}).get('attempts',[]):
            ids.update(attempt.get('retrieved_chunk_ids',[]))
        for name in ('pre_rerank_chunk_ids','keyword_candidates','vector_candidates'):
            ids.update(trace.get(name,[]))
        for cid in ids:
            self.store.citation(cid, actor)
        if not payload.get('context_chunk_ids') and payload.get('citations'):
            raise AccessError('answer_unavailable', 404)
        return payload

    def turns(self, actor, cid):
        self.conversation(actor, cid)
        with self.store.connect() as c:
            rows = self.sql(c, 'SELECT position,payload FROM app_turns WHERE conversation=? ORDER BY position', (cid,)).fetchall()
        result = []
        for row in rows:
            turn = json.loads(row['payload'])
            try:
                self.visible_answer(actor, turn['result'])
                result.append(dict(turn, position=row['position'], redacted=False))
            except AccessError:
                result.append({'position': row['position'], 'redacted': True,
                               'query': '[原会话涉及的资料已不可访问]', 'result': {'answer': '[回答已隐藏]', 'citations': []}})
        return result

    def append_turn(self, actor, cid, expected_version, query, result):
        self.visible_answer(actor, result)
        with self.store.connect() as c:
            changed = self.sql(c, 'UPDATE app_conversations SET version=version+1 WHERE id=? AND tenant=? AND actor=? AND version=?',
                (cid, actor.tenant_id, actor.user_id, expected_version))
            if changed.rowcount != 1:
                raise AccessError('conversation_changed_retry', 409)
            self.sql(c, 'INSERT INTO app_turns VALUES (?,?,?,?)', (uuid4().hex, cid, expected_version+1,
                json.dumps({'query': query, 'result': result}, ensure_ascii=False)))

    def delete_conversation(self, actor, cid):
        self.conversation(actor, cid)
        with self.store.connect() as c:
            self.sql(c, 'DELETE FROM app_turns WHERE conversation=?', (cid,))
            self.sql(c, 'DELETE FROM app_conversations WHERE id=? AND tenant=? AND actor=?', (cid, actor.tenant_id, actor.user_id))

    def record_answer(self, actor, query, result):
        self.visible_answer(actor, result)
        with self.store.connect() as c:
            self.sql(c, 'INSERT INTO app_answers VALUES (?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING',
                     (result['run_id'], actor.tenant_id, actor.user_id, json.dumps({'query': query, 'result': result}, ensure_ascii=False), now()))

    def answer(self, actor, run_id):
        self.store.run(run_id, actor)
        with self.store.connect() as c:
            row = self.sql(c, 'SELECT payload FROM app_answers WHERE run_id=? AND tenant=? AND actor=?',
                           (run_id, actor.tenant_id, actor.user_id)).fetchone()
        if row is None:
            raise AccessError('answer_not_found', 404)
        value = json.loads(row['payload'])
        self.visible_answer(actor, value['result'])
        return value

    def feedback(self, actor, run_id, value):
        self.answer(actor, run_id)
        visible = {c['document_id'] for c in self.store.authorized_chunks(actor)}
        if not set(value.get('expected_doc_ids', [])) <= visible:
            raise AccessError('feedback_document_unavailable', 404)
        with self.store.connect() as c:
            self.sql(c, 'INSERT INTO app_feedback VALUES (?,?,?,?,?,?) ON CONFLICT(run_id,tenant,actor) DO UPDATE SET payload=excluded.payload,created=excluded.created',
                (uuid4().hex, run_id, actor.tenant_id, actor.user_id, json.dumps(value, ensure_ascii=False), now()))

    def feedback_export(self, actor):
        with self.store.connect() as c:
            rows = self.sql(c, 'SELECT run_id,payload,created FROM app_feedback WHERE tenant=? AND actor=? ORDER BY created',
                            (actor.tenant_id, actor.user_id)).fetchall()
        records = []
        visible = {c['document_id'] for c in self.store.authorized_chunks(actor)}
        for row in rows:
            try:
                answer = self.answer(actor, row['run_id'])
            except AccessError:
                continue
            feedback = json.loads(row['payload'])
            if not set(feedback.get('expected_doc_ids', [])) <= visible:
                continue
            records.append({'run_id': row['run_id'], 'query': answer['query'], 'feedback': feedback,
                            'answer': answer['result']['answer'], 'created': row['created']})
        return {'format': 'rag-feedback-v1', 'records': records,
                'note': 'User labels require review; feedback is not automatically used as model training data.'}

    def create_job(self, actor, doc_id):
        jid = uuid4().hex
        with self.store.connect() as c:
            self.sql(c, 'INSERT INTO app_jobs VALUES (?,?,?,?,?,?,?)',
                     (jid, actor.tenant_id, actor.user_id, doc_id, 'queued', '{}', now()))
        return jid

    def job(self, actor, jid):
        with self.store.connect() as c:
            row = self.sql(c, 'SELECT * FROM app_jobs WHERE id=? AND tenant=? AND actor=?',
                           (jid, actor.tenant_id, actor.user_id)).fetchone()
        if row is None:
            raise AccessError('index_job_not_found', 404)
        result = dict(row)
        result['details'] = json.loads(result.pop('payload'))
        return result

    def claim_job(self, jid):
        with self.store.connect() as c:
            row = self.sql(c, "UPDATE app_jobs SET status='running' WHERE id=? AND status='queued'", (jid,))
            return row.rowcount == 1

    def finish_job(self, jid, status, payload):
        with self.store.connect() as c:
            self.sql(c, 'UPDATE app_jobs SET status=?,payload=? WHERE id=?', (status, json.dumps(payload), jid))
