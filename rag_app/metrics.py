"""Document relevance on ordered chunk results, compatible with the old Recall@4."""


def retrieval_metrics(ordered_chunk_ids, expected_doc_ids, authorized, k=4):
    expected = set(expected_doc_ids)
    if not expected:
        return {'recall_at_1': None, 'recall_at_4': None, 'hit_at_1': None, 'mrr_at_4': None}
    # Retain the retrieval order. Sorting a set before top-1 would invalidate Recall@1.
    documents = [authorized[cid]['document_id'] if cid in authorized else None
                 for cid in ordered_chunk_ids[:k]]
    first = set(documents[:1])
    return {
        'recall_at_1': len(expected & first) / len(expected),
        'recall_at_4': len(expected & set(documents)) / len(expected),
        'hit_at_1': float(bool(expected & first)),
        'mrr_at_4': next((1 / rank for rank, doc in enumerate(documents, 1) if doc in expected), 0.0),
    }
