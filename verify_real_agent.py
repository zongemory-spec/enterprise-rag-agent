"""Explicit bounded real-provider smoke; never prints keys or user tokens."""
import json
import os
import tempfile
from pathlib import Path
from rag_app.settings import configure_runtime
from rag_app.planner import HTTPPlanner
from rag_app.synthesis import ModelBudget,HTTPAnswerSynthesizer
from rag_app.workflow import execute
from rag_app.checkpoint import Checkpointer
from rag_app.service import Service
from rag_app.store import Store
from rag_app.security import Actor,AccessError
from init_demo import populate

if __name__=='__main__':
    configure_runtime(real=True)
    budget=ModelBudget(6)
    args=[os.environ['RAG_MODEL_URL'],os.environ['RAG_MODEL_KEY'],os.environ['RAG_MODEL_NAME'],budget]
    planner=HTTPPlanner(*args);synth=HTTPAnswerSynthesizer(*args)
    with tempfile.TemporaryDirectory() as temp:
        store=Store(Path(temp)/'db');populate(store);cp=Checkpointer(Path(temp)/'cp');service=Service(store)
        result=execute(service,cp,'查询我的工单 T1001 的当前状态，并查询退款审批条件，分别说明结果。不要猜测工单内容。',Actor('alice','demo',('support',)),planner,synthesizer=synth)
        tools=[c['tool'] for c in result['trace']]
        assert 'get_ticket_status' in tools and 'search_knowledge' in tools,result
        assert result['citations'] and '500' in result['answer'],result
        denied=False
        try:store.ticket('T1001',Actor('bob','demo',('engineering',)))
        except AccessError:denied=True
        assert denied
        report={'tools':tools,'answer':result['answer'],'model':synth.model,'chat_attempts':budget.used,'embedding_attempts':0,'citations':len(result['citations']),'bob_ticket_denied':denied,'usage_records':planner.usage_records+synth.usage_records,'scope':'One synthetic composite task; not a production-quality benchmark.'}
        Path('reports/real-agent-v3.2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
