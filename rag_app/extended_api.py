"""User-facing document, conversation and feedback endpoints."""
import json
from fastapi import Depends, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from rag_app.api import Question
from rag_app.security import AccessError


class ChatQuestion(Question):
    conversation_id: str | None=Field(default=None,pattern=r'^[a-f0-9]{32}$')


class VersionInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    expected_version:int=Field(ge=1)


class FeedbackInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    run_id:str=Field(min_length=1,max_length=64)
    rating:Literal['helpful','unhelpful']
    reason:Literal['correct','irrelevant','incomplete','unsupported','wrong_refusal','other']='other'
    comment:str=Field(default='',max_length=1000)
    corrected_answer:str=Field(default='',max_length=2000)
    expected_doc_ids:list[str]=Field(default_factory=list,max_length=20)
    expected_refusal:bool | None=None
    reviewed:bool=False

    @model_validator(mode='after')
    def consistent_labels(self):
        if self.reviewed and (self.expected_refusal is None or
                (self.expected_refusal and self.expected_doc_ids) or
                (not self.expected_refusal and not self.expected_doc_ids)):
            raise ValueError('Reviewed labels require either relevant documents or an expected refusal')
        return self


class CleanupInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    days:int=Field(default=30,ge=1,le=3650)
    all_personal_records:bool=False
    dry_run:bool=True
    prune_document_versions:bool=False
    keep_versions:int=Field(default=2,ge=1,le=10)


def install_extended_routes(app,service,state,documents,conversations,authenticated):
    @app.get('/privacy/export')
    def personal_export(actor=Depends(authenticated)):
        return app.state.retention.export(actor)

    @app.post('/privacy/cleanup')
    def cleanup(body:CleanupInput,actor=Depends(authenticated)):
        return app.state.retention.cleanup(actor,body.days,body.all_personal_records,body.dry_run,
                                           body.prune_document_versions,body.keep_versions)

    @app.post('/chat')
    def chat(body:ChatQuestion,actor=Depends(authenticated)):
        return conversations.ask(actor,body.query,body.conversation_id,body.method,body.top_k,body.rerank)

    @app.post('/conversations')
    def create_conversation(actor=Depends(authenticated)):
        return state.create_conversation(actor)

    @app.get('/conversations')
    def list_conversations(actor=Depends(authenticated)):
        return {'conversations':state.conversations(actor)}

    @app.get('/conversations/{conversation_id}')
    def conversation(conversation_id:str,actor=Depends(authenticated)):
        current=state.conversation(actor,conversation_id)
        return {'conversation_id':conversation_id,'version':current['version'],'turns':state.turns(actor,conversation_id)}

    @app.delete('/conversations/{conversation_id}')
    def delete_conversation(conversation_id:str,actor=Depends(authenticated)):
        state.delete_conversation(actor,conversation_id)
        return {'deleted':True}

    @app.get('/documents')
    def list_documents(actor=Depends(authenticated)):
        return {'documents':documents.listing(actor)}

    @app.post('/documents/upload')
    async def upload_document(background_tasks:BackgroundTasks,file:UploadFile=File(...),title:str=Form(...),
                              groups:str=Form('[]'),document_id:str | None=Form(None),
                              expected_version:int | None=Form(None),reindex:bool=Form(False),actor=Depends(authenticated)):
        try:
            content=await file.read(10*1024*1024+1)
            if len(content)>10*1024*1024:
                raise AccessError('upload_too_large',413)
            try:allowed_groups=json.loads(groups)
            except (ValueError,TypeError):raise AccessError('invalid_document_groups',422) from None
            result=documents.upload(actor,file.filename or 'document',content,title,allowed_groups,document_id,expected_version)
            if reindex and result['changed']:
                jid=documents.queue_index(actor,result['document_id'])
                background_tasks.add_task(documents.run_index_job,actor,jid)
                result['index_job_id']=jid
            return result
        finally:
            await file.close()

    @app.delete('/documents/{document_id}')
    def delete_document(document_id:str,body:VersionInput,actor=Depends(authenticated)):
        return documents.delete(actor,document_id,body.expected_version)

    @app.post('/documents/{document_id}/index')
    def index_document(document_id:str,background_tasks:BackgroundTasks,actor=Depends(authenticated)):
        jid=documents.queue_index(actor,document_id)
        background_tasks.add_task(documents.run_index_job,actor,jid)
        return {'job_id':jid,'status':'queued'}

    @app.get('/index-jobs/{job_id}')
    def index_job(job_id:str,actor=Depends(authenticated)):
        return state.job(actor,job_id)

    @app.post('/feedback')
    def feedback(body:FeedbackInput,actor=Depends(authenticated)):
        value=body.model_dump(exclude={'run_id'})
        state.feedback(actor,body.run_id,value)
        return {'saved':True,'run_id':body.run_id}

    @app.get('/feedback')
    def feedback_list(actor=Depends(authenticated)):
        data=state.feedback_export(actor)
        data['summary']={'total':len(data['records']),
            'helpful':sum(r['feedback']['rating']=='helpful' for r in data['records']),
            'reviewed':sum(r['feedback']['reviewed'] for r in data['records'])}
        return data

    @app.get('/feedback/export')
    def export_feedback(actor=Depends(authenticated)):
        return state.feedback_export(actor)
