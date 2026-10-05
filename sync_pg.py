import os
from rag_app.store import Store
from rag_app.pg_index import PGIndex
from rag_app.embedding import HTTPEmbedding

if __name__=="__main__":
    embedding=None
    if os.getenv("RAG_EMBEDDING","hash")=="real":
        embedding=HTTPEmbedding(os.environ["RAG_EMBED_URL"],os.environ["RAG_EMBED_KEY"],os.environ["RAG_EMBED_MODEL"],int(os.environ["RAG_EMBED_DIM"]))
    count=PGIndex(os.environ["RAG_PG_DSN"],embedding).sync(Store(os.getenv("RAG_DB","data/rag.sqlite3")))
    print(f"Indexed {count} authorized-version chunks. Model: "+(embedding.model_id if embedding else "lexical hash baseline"))

