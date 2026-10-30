"""Dify and Coze API adapters with fixed-scope or delegated-user authentication."""
import json
import os
from pathlib import Path
import secrets
from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from rag_app.api import Question
from rag_app.extended_api import ChatQuestion
from rag_app.evidence_policy import coverage
from rag_app.security import Actor, AccessError


class PlatformRegistry:
    def __init__(self,entries=()):
        self.entries=list(entries)
        for entry in self.entries:
            if (entry['platform'] not in ('coze','dify') or entry.get('mode','service') not in ('service','delegated')
                or not entry.get('token') or not entry.get('knowledge_ids') or not isinstance(entry.get('groups'),list)):
                raise ValueError('Invalid platform credential configuration')

    @classmethod
    def configured(cls):
        path=os.getenv('RAG_PLATFORM_AUTH_FILE')
        return cls(json.loads(Path(path).read_text(encoding='utf-8-sig'))) if path else cls()

    def authenticate(self,platform,request,users):
        header=request.headers.get('Authorization','')
        if not header.startswith('Bearer '):raise AccessError('platform_authentication_required',401)
        for entry in self.entries:
            if entry['platform']==platform and secrets.compare_digest(header[7:].encode(),entry['token'].encode()):
                actor=Actor(entry['user_id'],entry['tenant_id'],tuple(entry['groups']))
                if entry.get('mode','service')=='delegated':
                    token=request.headers.get('X-RAG-User-Token','')
                    user=users.authenticate('Bearer '+token)
                    if user.tenant_id!=actor.tenant_id:raise AccessError('platform_tenant_mismatch',403)
                    actor=Actor(user.user_id,user.tenant_id,tuple(sorted(set(user.groups)&set(actor.groups))))
                return actor,set(entry['knowledge_ids'])
        raise AccessError('invalid_platform_credentials',401)


class RetrievalSettings(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    top_k:int=Field(ge=1,le=8)
    score_threshold:float=Field(ge=0,le=1)


class DifyRetrieval(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    knowledge_id:str=Field(min_length=1,max_length=100)
    query:str=Field(min_length=1,max_length=2000)
    retrieval_setting:RetrievalSettings
    metadata_condition:dict | None=None


def install_platform_routes(app,service,state,conversations,users,registry):
    def dify_auth(request:Request):return registry.authenticate('dify',request,users)
    def coze_auth(request:Request):return registry.authenticate('coze',request,users)

    def records(query,actor,method,top_k,rerank):
        result=service.retrieve(query,actor,method,top_k,rerank)
        rows=[]
        for chunk in result['chunks']:
            fresh=service.store.citation(chunk['chunk_id'],actor)
            rows.append({'content':fresh['text'],'title':fresh['title'],
                'score':round(coverage(query,fresh['title']+'\n'+fresh['text']),6),
                'metadata':{k:fresh[k] for k in ('document_id','chunk_id','version','source','location')}})
        if service.store.index_version!=result['index_version']:raise AccessError('index_changed_retry',409)
        return rows,result['evidence_check']

    @app.post('/integrations/dify/retrieval',operation_id='difyKnowledgeRetrieval')
    def dify_retrieval(body:DifyRetrieval,context=Depends(dify_auth)):
        actor,knowledge_ids=context
        if body.knowledge_id not in knowledge_ids:raise AccessError('knowledge_not_found',404)
        # Never silently ignore a filter that could narrow access or relevance.
        if body.metadata_condition:raise AccessError('metadata_condition_not_supported',422)
        rows,_=records(body.query,actor,os.getenv('RAG_PLATFORM_METHOD','bm25'),body.retrieval_setting.top_k,
                       os.getenv('RAG_PLATFORM_RERANK','off')=='on')
        return {'records':[r for r in rows if r['score']>=body.retrieval_setting.score_threshold]}

    @app.post('/integrations/dify/ask',operation_id='difyAskKnowledge')
    def dify_ask(body:ChatQuestion,context=Depends(dify_auth)):
        actor,_=context
        return conversations.ask(actor,body.query,body.conversation_id,body.method,body.top_k,body.rerank)

    @app.post('/integrations/coze/ask',operation_id='cozeAskKnowledge')
    def coze_ask(body:ChatQuestion,context=Depends(coze_auth)):
        actor,_=context
        return conversations.ask(actor,body.query,body.conversation_id,body.method,body.top_k,body.rerank)

    @app.post('/integrations/coze/search',operation_id='cozeSearchKnowledge')
    def coze_search(body:Question,context=Depends(coze_auth)):
        actor,_=context
        rows,check=records(body.query,actor,body.method,body.top_k,body.rerank)
        return {'records':rows,'evidence_check':check}
