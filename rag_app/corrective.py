"""A bounded LangGraph retrieve/check/rewrite/retry subgraph for the demo."""
from typing import TypedDict,Any
from langgraph.graph import StateGraph,START,END
from rag_app.query_rewrite import canonicalize
from rag_app.tracing import span


class State(TypedDict,total=False):
    result:Any
    rewritten:str
    attempts:list


def retrieve_with_correction(query,retrieve_once,enabled=True):
    def attempt(search_query):
        with span('corrective.retrieve'):
            result=retrieve_once(search_query)
        return result,{'query':search_query,'status':result['evidence_check']['status'],
                       'retrieved_chunk_ids':result['retrieved_chunk_ids']}

    def first(_):
        result,record=attempt(query)
        return {'result':result,'attempts':[record]}

    def rewrite(_):
        with span('corrective.rewrite'):
            return {'rewritten':canonicalize(query)}

    def retry(state):
        result,record=attempt(state['rewritten'])
        return {'result':result,'attempts':state['attempts']+[record]}

    graph=StateGraph(State)
    graph.add_node('retrieve',first)
    graph.add_node('rewrite',rewrite)
    graph.add_node('retry',retry)
    graph.add_edge(START,'retrieve')
    graph.add_conditional_edges('retrieve',lambda s:'rewrite' if enabled and s['result']['evidence_check']['status']=='insufficient' else END,
                                {'rewrite':'rewrite',END:END})
    graph.add_conditional_edges('rewrite',lambda s:'retry' if s['rewritten']!=query else END,{'retry':'retry',END:END})
    graph.add_edge('retry',END)
    state=graph.compile().invoke({},config={'recursion_limit':8})
    result=state['result']
    result['retrieval_trace']['correction']={'enabled':enabled,'strategy':'reviewed-domain-aliases',
        'attempt_limit':2,'attempts':state['attempts'],
        'outcome':'supported' if result['evidence_check']['status']=='accepted' else 'insufficient',
        'note':'No retry on provider/authorization errors; no useful rewrite means no repeated request.'}
    return result
