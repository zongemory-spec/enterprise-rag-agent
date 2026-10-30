"""Permission-aware follow-up resolution. Reuse authorized source titles, not old answers."""
import re
from rag_app.security import AccessError

FOLLOWUP = re.compile(r'^(那|那么|这个|那个|它|这些|还需要|还有|需要什么|需要哪些|具体|what about|and |how about)', re.I)


class Conversations:
    def __init__(self, service, state):
        self.service, self.state = service, state

    def ask(self, actor, query, conversation_id=None, method='bm25', top_k=4, rerank=False):
        cid = conversation_id or self.state.create_conversation(actor)['conversation_id']
        current = self.state.conversation(actor, cid)
        if current['version'] >= 100:
            raise AccessError('conversation_turn_limit', 409)
        resolved = query
        rewritten = False
        if FOLLOWUP.search(query.strip()):
            history = self.state.turns(actor, cid)
            latest = next((t for t in reversed(history) if not t['redacted'] and
                           t['result'].get('citations') and not t['result'].get('refused')), None)
            if latest is None:
                # A follow-up without an accessible subject should not search unrelated documents.
                result = self.service.ask('', actor, method, top_k, rerank)
                result['answer'] = '请补充你要追问的主题；当前没有可用的前文资料。'
                result['refusal_reason'] = 'followup_requires_clarification'
                result['clarification']={'needed':True,'question':'你想追问哪个主题？','choices':[]}
            else:
                titles = []
                for citation in latest['result']['citations']:
                    row = self.service.store.citation(citation['chunk_id'], actor)
                    if row['title'] not in titles:
                        titles.append(row['title'])
                from rag_app.evidence_policy import focus_terms
                from rag_app.bm25 import tokens
                matches=[title for title in titles if focus_terms(query)&set(tokens(title))]
                if len(titles)>1 and len(matches)!=1:
                    result=self.service.ask('',actor,method,top_k,rerank)
                    result['answer']='请先明确你想追问哪个主题：'+'、'.join(titles[:4])+'。'
                    result['refusal_reason']='ambiguous_followup'
                    result['clarification']={'needed':True,'question':'你想追问哪个主题？','choices':titles[:4]}
                    result['clarification_source_ids']=[c['chunk_id'] for c in latest['result']['citations']]
                else:
                    resolved = (' '.join(matches or titles[:1]) + ' ' + query)[:2000]
                    rewritten = True
                    result = self.service.ask(resolved, actor, method, top_k, rerank)
        else:
            result = self.service.ask(query, actor, method, top_k, rerank)
        result.update(conversation_id=cid, conversation_version=current['version']+1,
                      resolved_query=resolved, query_rewritten=rewritten)
        self.state.append_turn(actor, cid, current['version'], query, result)
        self.state.record_answer(actor, query, result)
        return result
