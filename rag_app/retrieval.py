"""Keyword and deterministic lexical-hash baselines. Hash vectors are NOT semantic embeddings."""
import hashlib
import math
import re

MODEL_ID = "lexical-hash-sha256-256-v1"
DIMENSIONS = 256
STOP = {"what","is","the","and","of","please","tell","me","how"}
def terms(text):
    text = text.lower()
    words = [w for w in re.findall(r"[a-z0-9_-]+",text) if w not in STOP]
    for run in re.findall(r"[\u4e00-\u9fff]+",text):
        words.extend(run[i:i+2] for i in range(len(run)-1))
    return set(words)

def embed(text):
    vector = [0.0]*DIMENSIONS
    for token in terms(text):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4],"big")%DIMENSIONS] += 1 if digest[4]&1 else -1
    norm = math.sqrt(sum(v*v for v in vector)) or 1
    return [v/norm for v in vector]

def dot(a,b):
    return sum(x*y for x,y in zip(a,b))

def rank(query,chunks,method="keyword",top_k=4):
    q = terms(query)
    if not q:
        return []
    qv = embed(query)
    scores = []
    for chunk in chunks:
        searchable = chunk["title"]+" "+chunk["text"]
        tokens = terms(searchable)
        if method == "keyword":
            score = len(q & tokens) / len(q)
        elif method == "hash-vector":
            score = dot(qv,embed(searchable))
        else:
            raise ValueError("Unsupported retrieval method")
        if score >= .15:
            scores.append((score,chunk))
    scores.sort(key=lambda x:(-x[0],x[1]["chunk_id"]))
    return [dict(chunk,score=round(score,6)) for score,chunk in scores[:top_k]]

