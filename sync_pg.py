import argparse,os
from rag_app.settings import configure_runtime,open_store
from rag_app.pg_native_index import NativePGIndex
from rag_app.embedding import HTTPEmbedding
from init_demo import populate
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--real",action="store_true",help="Enable billable semantic embedding requests")
    args=parser.parse_args()
    configure_runtime(real=args.real)
    store=open_store()
    if store.backend!="postgresql":raise SystemExit("Configure PostgreSQL first")
    populate(store)
    embedding=None
    if args.real:
        embedding=HTTPEmbedding(os.environ["RAG_EMBED_URL"],os.environ["RAG_EMBED_KEY"],os.environ["RAG_EMBED_MODEL"],int(os.environ["RAG_EMBED_DIM"]))
    index=NativePGIndex(store,embedding)
    print({"indexed_chunks":index.sync(),"model":index.model_id})
