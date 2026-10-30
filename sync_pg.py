import argparse,os
from rag_app.settings import configure_runtime,open_store
from rag_app.pg_native_index import NativePGIndex
from rag_app.embedding import HTTPEmbedding
from init_demo import populate
if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--real",action="store_true",help="Enable billable semantic embedding requests")
    parser.add_argument('--env-file',help='Explicitly load a local environment file')
    args=parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        if not os.path.isfile(args.env_file):parser.error('Environment file not found')
        load_dotenv(args.env_file,override=False)
    configure_runtime(semantic=args.real)
    store=open_store()
    if store.backend!="postgresql":raise SystemExit("Configure PostgreSQL first")
    populate(store)
    embedding=None
    if args.real:
        from rag_app.request_budget import PersistentBudget
        embedding=HTTPEmbedding(os.environ["RAG_EMBED_URL"],os.environ["RAG_EMBED_KEY"],os.environ["RAG_EMBED_MODEL"],int(os.environ["RAG_EMBED_DIM"]),PersistentBudget(os.environ['RAG_BUDGET_DB']))
    index=NativePGIndex(store,embedding)
    if index.status()['ready']:print({'status':'already_ready','model':index.model_id})
    else:print({"indexed_chunks":index.sync(),"model":index.model_id})
