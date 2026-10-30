"""User-scoped preview/apply cleanup for the personal demo. No scheduler or new service."""
import json
from datetime import datetime,timezone,timedelta


def older(value,cutoff):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))<cutoff


class Retention:
    def __init__(self,state,checkpoints=None):
        self.state,self.store,self.checkpoints=state,state.store,checkpoints

    def export(self,actor):
        conversations=[]
        with self.store.connect() as c:
            rows=self.state.sql(c,'SELECT id FROM app_conversations WHERE tenant=? AND actor=?',(actor.tenant_id,actor.user_id)).fetchall()
            answers=self.state.sql(c,'SELECT run_id FROM app_answers WHERE tenant=? AND actor=?',(actor.tenant_id,actor.user_id)).fetchall()
        for row in rows:
            conversations.append({'conversation_id':row['id'],'turns':self.state.turns(actor,row['id'])})
        visible=[]
        from rag_app.security import AccessError
        for row in answers:
            try:visible.append(dict(self.state.answer(actor,row['run_id']),run_id=row['run_id']))
            except AccessError:pass
        return {'format':'personal-records-v1','conversations':conversations,'answers':visible,
                'feedback':self.state.feedback_export(actor),'note':'Exports currently accessible personal records, not tokens or document files.'}

    def cleanup(self,actor,days=30,all_records=False,dry_run=True,prune_versions=False,keep_versions=2):
        if type(days) is not int or not 1<=days<=3650 or type(keep_versions) is not int or not 1<=keep_versions<=10:
            raise ValueError('Invalid retention settings')
        cutoff=datetime.now(timezone.utc)-timedelta(days=days)
        scope=(actor.tenant_id,actor.user_id)
        sql=self.state.sql
        with self.store.connect() as c:
            if self.store.backend=='sqlite':c.execute('BEGIN IMMEDIATE')
            else:c.execute('SELECT pg_advisory_xact_lock(hashtext(current_schema()),27183)')
            suffix=' FOR UPDATE' if self.store.backend=='postgresql' else ''
            conversations=[dict(r) for r in sql(c,'SELECT * FROM app_conversations WHERE tenant=? AND actor=?'+suffix,scope).fetchall()]
            answers=[dict(r) for r in sql(c,'SELECT * FROM app_answers WHERE tenant=? AND actor=?',scope).fetchall()]
            answer_dates={r['run_id']:r['created'] for r in answers}
            delete_conversations=[];protected_runs=set()
            for row in conversations:
                turns=sql(c,'SELECT payload FROM app_turns WHERE conversation=?',(row['id'],)).fetchall()
                runs={json.loads(t['payload'])['result'].get('run_id') for t in turns}-{None}
                activity=max([row['created']]+[answer_dates[r] for r in runs if r in answer_dates])
                if all_records or older(activity,cutoff):delete_conversations.append(row['id'])
                else:protected_runs.update(runs)
            delete_answers={r['run_id'] for r in answers if r['run_id'] not in protected_runs and (all_records or older(r['created'],cutoff))}
            feedback=[dict(r) for r in sql(c,'SELECT id,run_id,created FROM app_feedback WHERE tenant=? AND actor=?',scope).fetchall()]
            delete_feedback=[r['id'] for r in feedback if all_records or r['run_id'] in delete_answers or older(r['created'],cutoff)]
            jobs=[dict(r) for r in sql(c,'SELECT id,status,created FROM app_jobs WHERE tenant=? AND actor=?',scope).fetchall()]
            delete_jobs=[r['id'] for r in jobs if r['status'] in ('succeeded','failed') and (all_records or older(r['created'],cutoff))]
            delete_runs=delete_answers
            if all_records:
                delete_runs={r['run_id'] for r in sql(c,'SELECT run_id FROM runs WHERE tenant=? AND actor=?',scope).fetchall()}
            versions=[]
            if prune_versions:
                documents=sql(c,'SELECT document_id,version,active FROM documents WHERE tenant_id=? AND owner=? ORDER BY document_id,version DESC',scope).fetchall()
                counts={}
                for row in documents:
                    counts[row['document_id']]=counts.get(row['document_id'],0)+1
                    if not row['active'] and counts[row['document_id']]>keep_versions:
                        versions.append((row['document_id'],row['version']))
            counts={'conversations':len(delete_conversations),'answers':len(delete_answers),'feedback':len(delete_feedback),
                    'completed_jobs':len(delete_jobs),'runs':len(delete_runs),'inactive_document_versions':len(versions),
                    'active_jobs_kept':sum(r['status'] in ('queued','running') for r in jobs)}
            if not dry_run:
                for cid in delete_conversations:
                    sql(c,'DELETE FROM app_turns WHERE conversation=?',(cid,))
                    sql(c,'DELETE FROM app_conversations WHERE id=? AND tenant=? AND actor=?',(cid,*scope))
                for table,column,ids in [('app_feedback','id',delete_feedback),('app_answers','run_id',delete_answers),
                                         ('app_jobs','id',delete_jobs),('runs','run_id',delete_runs)]:
                    for value in ids:sql(c,f'DELETE FROM {table} WHERE {column}=? AND tenant=? AND actor=?',(value,*scope))
                for doc_id,version in versions:
                    if self.store.backend=='postgresql':
                        exists=c.execute("SELECT to_regclass(current_schema()||'.embeddings') AS name").fetchone()['name']
                        if exists:sql(c,'DELETE FROM embeddings WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE document_id=? AND version=?)',(doc_id,version))
                    sql(c,'DELETE FROM chunks WHERE document_id=? AND version=?',(doc_id,version))
                    sql(c,'DELETE FROM documents WHERE document_id=? AND version=? AND active=0',(doc_id,version))
        checkpoints={'deleted_or_selected':0,'active_kept':0}
        if all_records and self.checkpoints:
            # Checkpoints have no creation time; age-based cleanup does not guess their age.
            checkpoints=self.checkpoints.clear_inactive(actor,dry_run)
        return {'dry_run':dry_run,'mode':'all-personal-records' if all_records else 'older-than-cutoff',
                'cutoff':cutoff.isoformat(),'counts':counts,'checkpoints':checkpoints,
                'note':'Active documents, credentials, audit metadata and budgets are retained. Queued/running jobs are retained. '
                       'Optional version pruning only affects owned inactive versions. Stop requests before clearing personal records.'}
