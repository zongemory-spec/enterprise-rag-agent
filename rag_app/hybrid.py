"""Reciprocal rank fusion of independently authorized candidate lists."""
def fuse(keyword,vector,top_k=4,constant=60):
    merged={}
    for channel,rows in [('keyword',keyword),('vector',vector)]:
        seen=set()
        for position,row in enumerate(rows,1):
            cid=row['chunk_id']
            if cid in seen:continue
            seen.add(cid)
            item=merged.setdefault(cid,dict(row,rrf_score=0.,channel_ranks={}))
            item['rrf_score']+=1./(constant+position)
            item['channel_ranks'][channel]=position
    ordered=sorted(merged.values(),key=lambda r:(-r['rrf_score'],r['chunk_id']))
    return [dict(row,score=row['rrf_score']) for row in ordered[:top_k]]
