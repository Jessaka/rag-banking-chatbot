import os, sys, json, traceback
# Add project root to PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.retrieval.bm25_retriever import bm25_search
from src.retrieval.vector_retriever import vector_search
from src.retrieval.hybrid import hybrid_search
from src.retrieval.reranker import rerank

QUERY = "Jaké typy úvěrů banka nabízí?"
TOP_K = 10

def src_path(doc):
    return (
        doc.metadata.get('source_url')
        or doc.metadata.get('url')
        or doc.metadata.get('file_name')
        or doc.metadata.get('chunk_id')
        or '<unknown>'
    )

def collect(docs, score_key):
    return [
        {
            'score': round(doc.metadata.get(score_key, 0), 6),
            'source_path': src_path(doc)
        }
        for doc in docs[:TOP_K]
    ]

def safe_call(func, *args, **kwargs):
    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception:
        return None, traceback.format_exc()

if __name__ == '__main__':
    output = {}
    # BM25
    bm25_res, bm25_err = safe_call(bm25_search, QUERY, top_k=TOP_K)
    if bm25_err:
        print('Error during BM25 search:', file=sys.stderr)
        print(bm25_err, file=sys.stderr)
    else:
        output['bm25'] = collect(bm25_res, 'bm25_score')

    # Qdrant
    qdrant_res, qdrant_err = safe_call(vector_search, QUERY, top_k=TOP_K)
    if qdrant_err:
        print('Error during Qdrant (vector) search:', file=sys.stderr)
        print(qdrant_err, file=sys.stderr)
    else:
        output['qdrant'] = collect(qdrant_res, 'vector_score')

    # Hybrid
    hybrid_res, hybrid_err = safe_call(hybrid_search, query=QUERY, top_k=TOP_K)
    if hybrid_err:
        print('Error during Hybrid search:', file=sys.stderr)
        print(hybrid_err, file=sys.stderr)
    else:
        output['hybrid'] = collect(hybrid_res, 'hybrid_score')

    # Rerank (uses hybrid results as input)
    if hybrid_res is not None:
        rerank_res, rerank_err = safe_call(rerank, QUERY, hybrid_res, top_k=TOP_K)
        if rerank_err:
            print('Error during Rerank:', file=sys.stderr)
            print(rerank_err, file=sys.stderr)
        else:
            output['rerank'] = collect(rerank_res, 'rerank_score')
    else:
        print('Skipping rerank because hybrid results are unavailable.', file=sys.stderr)

    # Print JSON result
    print(json.dumps(output, ensure_ascii=False, indent=2))
