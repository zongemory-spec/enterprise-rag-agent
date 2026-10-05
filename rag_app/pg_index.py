"""Optional pgvector index. SQLite remains the authoritative version/ACL store."""
import json
from rag_app.retrieval import MODEL_ID, DIMENSIONS, embed

class PGIndex:
    def __init__(self,dsn,embedder=None):
        self.dsn=dsn
        self.embedder=embedder
        self.model_id=embedder.model_id if embedder else MODEL_ID
        self.dimensions=embedder.dimensions if embedder else DIMENSIONS

    def vectors(self,texts):
        return self.embedder.embed(texts) if self.embedder else [embed(t) for t in texts]

    def connect(self):
        import psycopg
        return psycopg.connect(self.dsn,connect_timeout=5,options="-c statement_timeout=5000")

    def sync(self,store):
        generation,rows=store.snapshot_all()
        vectors=self.vectors([r["title"]+" "+r["text"] for r in rows])
        with self.connect() as c:
            c.execute("CREATE EXTENSION IF NOT EXISTS vector")
            c.execute("""CREATE TABLE IF NOT EXISTS rag_vectors (
                chunk_id text NOT NULL, model_id text NOT NULL, generation text NOT NULL,
                document_id text NOT NULL, version integer NOT NULL, tenant text NOT NULL,
                owner_id text NOT NULL, allowed_groups text[] NOT NULL,
                text_content text NOT NULL, embedding vector NOT NULL,
                PRIMARY KEY(chunk_id,model_id))""")
            # Replace only this embedding model's local demo index, atomically.
            c.execute("DELETE FROM rag_vectors WHERE model_id=%s",(self.model_id,))
            for row,vector in zip(rows,vectors):
                c.execute("INSERT INTO rag_vectors VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                    (row["chunk_id"],self.model_id,generation,row["document_id"],row["version"],row["tenant_id"],
                     row["owner"],json.loads(row["allowed_groups"]),row["text"],json.dumps(vector)))
        return len(rows)

    def retrieve(self,store,actor,query,top_k=4):
        generation=store.index_version
        vector=self.vectors([query])[0]
        with self.connect() as c:
            rows=c.execute("""SELECT chunk_id,1-(embedding <=> %s::vector) AS score FROM rag_vectors
              WHERE model_id=%s AND generation=%s AND tenant=%s
              AND (owner_id=%s OR allowed_groups && %s::text[])
              ORDER BY embedding <=> %s::vector,chunk_id LIMIT %s""",
              (json.dumps(vector),self.model_id,generation,actor.tenant_id,actor.user_id,["public",*actor.groups],json.dumps(vector),top_k)).fetchall()
        output=[]
        from rag_app.security import AccessError
        for cid,score in rows:
            if score < .15:continue
            try:row=store.citation(cid,actor)
            except AccessError:continue
            output.append(dict(row,score=float(score)))
        if store.index_version != generation:
            raise AccessError("index_changed_retry",409)
        return output

