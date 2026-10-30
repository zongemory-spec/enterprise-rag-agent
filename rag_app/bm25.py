"""Okapi BM25 over the caller's authorized corpus; frequencies are preserved."""
import logging
import re
from functools import lru_cache

import jieba
from rank_bm25 import BM25Okapi

jieba.setLogLevel(logging.WARNING)
STOP = frozenset(('的', '了', '是', '什么', '怎么', '如何', '请', '请问', '告诉', '我',
                  'the', 'a', 'an', 'is', 'are', 'what', 'how', 'please'))


@lru_cache(maxsize=1)
def tokenizer():
    # Avoid writing jieba.cache outside the application workspace.
    engine = jieba.Tokenizer()
    from pathlib import Path
    import tempfile
    engine.tmp_dir = tempfile.gettempdir()
    return engine


def tokens(text):
    """Word segmentation plus Chinese bigrams handles compounds and partial names."""
    result = []
    for run in re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+', text.lower()):
        if re.fullmatch(r'[a-z0-9_-]+', run):
            if run not in STOP:
                result.append(run)
        else:
            result.extend(w for w in tokenizer().cut(run, HMM=False) if w not in STOP and w.strip())
            result.extend('bi:' + run[i:i+2] for i in range(len(run)-1)
                          if run[i:i+2] not in STOP)
    return result


def rank_bm25(query, chunks, top_k=4):
    query_tokens = list(dict.fromkeys(tokens(query)))
    if not chunks or not query_tokens or top_k <= 0:
        return []
    corpus = [tokens(c['title'] + ' ' + c['text']) for c in chunks]
    if not any(corpus):
        return []
    index = BM25Okapi(corpus, k1=1.5, b=0.75)
    scores = index.get_scores(query_tokens)
    vocabulary = set(query_tokens)
    # BM25 scores are corpus-relative, so do not reuse the old cosine threshold.
    # For tiny corpora IDF can be nonpositive; a lexical match still is a candidate.
    ranked = [(float(score), row) for score, row, words in zip(scores, chunks, corpus)
              if vocabulary.intersection(words)]
    ranked.sort(key=lambda item: (-item[0], item[1]['chunk_id']))
    return [dict(row, score=round(score, 8)) for score, row in ranked[:top_k]]
