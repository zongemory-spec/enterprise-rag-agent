import argparse
import os
import uvicorn
from rag_app.settings import configure_runtime,open_store
from init_demo import main

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--real",action="store_true",help="Explicitly enable billable model calls")
    parser.add_argument("--port",type=int,default=8003)
    args=parser.parse_args()
    configure_runtime(real=args.real)
    main()
    uvicorn.run("rag_app.api:create_app",factory=True,host="127.0.0.1",port=args.port,access_log=False)

