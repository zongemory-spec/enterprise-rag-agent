"""Four offline showcase scenarios, using disposable synthetic data only."""
import argparse
import json
from pathlib import Path
import tempfile
from init_demo import populate
from rag_app.application_state import ApplicationState
from rag_app.conversation import Conversations
from rag_app.retention import Retention
from rag_app.sections import split_sections
from rag_app.security import Actor
from rag_app.service import Service
from rag_app.store import Store


def walkthrough():
    with tempfile.TemporaryDirectory() as folder:
        store=Store(Path(folder)/'demo.sqlite3');populate(store)
        actor=Actor('alice','demo',('support',));service=Service(store,corrective=True,expand_context=True);state=ApplicationState(store)
        corrected=service.ask('报账',actor,'bm25')
        attempts=corrected['retrieval_trace']['correction']['attempts']
        assert not corrected['refused'] and len(attempts)==2
        text='# Orion travel\n## Cabin approval\n'+('Cabin allowance details. '*25)+'\nManager approval is required.\n## Equipment\nEquipment follows a separate policy.'
        store.upsert({'document_id':'SHOWCASE','version':1,'title':'Orion travel','source':'synthetic-showcase',
            'tenant_id':'demo','owner':'alice','allowed_groups':[],'created_at':'2026-10-29'},text,split_sections(text,140))
        expanded=service.retrieve('Cabin allowance',actor,'bm25',1)
        added=expanded['retrieval_trace']['section_context_chunk_ids']
        assert added and len(expanded['chunks'])>len(expanded['retrieved_chunk_ids'])
        conversations=Conversations(service,state)
        initial=conversations.ask(actor,'差旅报销和入职材料分别有什么要求？')
        clarified=conversations.ask(actor,'那具体呢？',initial['conversation_id'])
        assert clarified['refusal_reason']=='ambiguous_followup' and len(clarified['clarification']['choices'])>=2
        preview=Retention(state).cleanup(actor,all_records=True)
        assert preview['dry_run'] and preview['counts']['conversations']==1
        applied=Retention(state).cleanup(actor,all_records=True,dry_run=False)
        assert not state.conversations(actor)
        return {'kind':'offline-showcase-scenarios','version':'4.2','scenarios':{
            'corrective_retrieval':{'passed':True,'queries':[a['query'] for a in attempts],'attempts':len(attempts)},
            'parent_section_context':{'passed':True,'retrieved_children':len(expanded['retrieved_chunk_ids']),
                                      'context_chunks':len(expanded['chunks']),'added_siblings':len(added)},
            'clarification':{'passed':True,'choices':clarified['clarification']['choices']},
            'personal_cleanup':{'passed':True,'preview':preview['counts'],'applied':applied['counts']}},
            'note':'Feature demonstrations over disposable synthetic data; not a model-quality benchmark. No external API calls.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out');args=parser.parse_args()
    if args.out and Path(args.out).exists():parser.error('Choose a fresh showcase report path')
    report=walkthrough()
    if args.out:
        Path(args.out).parent.mkdir(parents=True,exist_ok=True)
        Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
