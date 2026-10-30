"""Deterministic regression gate. Missing/NaN metrics fail, never silently pass."""
import argparse
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def check_report(report,config,baseline=None):
    failures=[];checked=[]
    if report.get('split')!=config['split']:failures.append('wrong_split')
    if report.get('dataset_sha256')!=config['dataset_sha256']:failures.append('wrong_dataset')
    if report.get('mode')!='offline-synthetic':failures.append('wrong_runtime_mode')
    if baseline and (baseline.get('dataset_sha256')!=report.get('dataset_sha256') or baseline.get('split')!=report.get('split')):
        failures.append('baseline_dataset_mismatch')
    for method in config['methods']:
        matches=[r for r in report.get('results',[]) if r.get('method')==method and r.get('rerank') is False]
        if len(matches)!=1:
            failures.append(method+':missing_or_duplicate_result');continue
        result=matches[0];metrics=result.get('metrics',{});rows=result.get('rows',[])
        if metrics.get('n')!=config['question_count'] or len(rows)!=config['question_count'] or len({r.get('question_id') for r in rows})!=len(rows):
            failures.append(method+':wrong_question_inventory')
        for key,minimum in config['minimum'].items():
            value=metrics.get(key)
            if not number(value) or value+1e-9<minimum:failures.append(method+':below_minimum:'+key)
        for key,maximum in config['maximum'].items():
            value=metrics.get(key)
            if not number(value) or value-1e-9>maximum:failures.append(method+':above_maximum:'+key)
        leaks=metrics.get('leak_events',{})
        if any(not number(leaks.get(key)) or leaks[key]!=0 for key in ('retrieval_leaks','context_leaks','output_leaks')):
            failures.append(method+':permission_leak_or_missing_metric')
        if baseline:
            previous=[r for r in baseline.get('results',[]) if r.get('method')==method and r.get('rerank') is False]
            if len(previous)!=1:failures.append(method+':missing_baseline')
            else:
                old=previous[0].get('metrics',{});tol=config['baseline_tolerance']
                for key,tolerance in [('recall_at_1_macro','recall_at_1_drop'),('recall_at_4_macro','recall_at_4_drop'),('correct_refusal_rate','correct_refusal_drop')]:
                    if not number(old.get(key)) or not number(metrics.get(key)) or old[key]-metrics[key]>tol[tolerance]+1e-9:
                        failures.append(method+':regressed:'+key)
                key='false_refusal_rate'
                if not number(old.get(key)) or not number(metrics.get(key)) or metrics[key]-old[key]>tol['false_refusal_increase']+1e-9:
                    failures.append(method+':regressed:'+key)
        checked.append(method)
    return {'passed':not failures,'checked_methods':checked,'failures':failures,
            'note':config['note']}


def main():
    p=argparse.ArgumentParser();p.add_argument('--report',required=True)
    p.add_argument('--config',default=str(ROOT/'evaluation_gate.json'))
    p.add_argument('--baseline');p.add_argument('--out',required=True)
    a=p.parse_args();out=Path(a.out)
    if out.exists():p.error('Choose a fresh gate report path')
    cfg=json.loads(Path(a.config).read_text(encoding='utf-8-sig'))
    baseline_path=Path(a.baseline) if a.baseline else ROOT/cfg['baseline_report']
    report=json.loads(Path(a.report).read_text(encoding='utf-8-sig'))
    baseline=json.loads(baseline_path.read_text(encoding='utf-8-sig'))
    result=check_report(report,cfg,baseline)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
