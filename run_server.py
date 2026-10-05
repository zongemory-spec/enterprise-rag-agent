import argparse
import os
import uvicorn
from rag_app.settings import configure_runtime,open_store
from init_demo import main

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--real",action="store_true",help="Explicitly enable billable model calls")
    parser.add_argument('--semantic',action='store_true',help='Enable paid embedding queries; build the index explicitly first')
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8003)
    args=parser.parse_args()
    configure_runtime(real=args.real,semantic=args.semantic)
    main()
    if os.getenv("RAG_STORE")=="postgresql" and not args.real and not args.semantic:
        from rag_app.pg_native_index import NativePGIndex
        NativePGIndex(open_store()).sync()
    uvicorn.run("rag_app.api:create_app",factory=True,host=args.host,port=args.port,access_log=False)

