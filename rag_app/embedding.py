"""Opt-in compatible embedding endpoint. Never called by offline tests or default startup."""
import math
import httpx

class HTTPEmbedding:
    def __init__(self,base_url,api_key,model,dimensions):
        if not api_key or not model or dimensions<1:raise ValueError("Embedding configuration required")
        self.base_url,self.api_key,self.model=base_url,api_key,model
        self.dimensions=dimensions
        self.model_id=f"http:{model}:{dimensions}"

    def embed(self,texts):
        vectors=[]
        with httpx.Client(timeout=20) as c:
            for start in range(0,len(texts),16):
                try:
                    response=c.post(self.base_url.rstrip("/")+"/embeddings",
                        headers={"Authorization":"Bearer "+self.api_key},
                        json={"model":self.model,"input":texts[start:start+16]})
                    response.raise_for_status()
                    batch=sorted(response.json()["data"],key=lambda row:row["index"])
                    if [row["index"] for row in batch] != list(range(len(texts[start:start+16]))):raise ValueError()
                    for row in batch:
                        v=row["embedding"]
                        if len(v)!=self.dimensions or not all(type(x) in (float,int) and math.isfinite(x) for x in v):
                            raise ValueError()
                        if sum(x*x for x in v)==0:raise ValueError()
                        vectors.append(v)
                except (httpx.HTTPError,KeyError,TypeError,ValueError):
                    raise RuntimeError("Embedding request failed; upstream details withheld") from None
        return vectors

