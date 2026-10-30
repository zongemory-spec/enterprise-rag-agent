"""Generate a private platform service credential; never print the token."""
import argparse
import json
from pathlib import Path
import secrets


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--platform',choices=['coze','dify'],required=True)
    p.add_argument('--tenant',required=True)
    p.add_argument('--user',required=True)
    p.add_argument('--groups',nargs='*',default=[])
    p.add_argument('--knowledge-ids',nargs='+',default=['enterprise'])
    p.add_argument('--mode',choices=['service','delegated'],default='delegated')
    p.add_argument('--out',default='data/platform_auth.json')
    a=p.parse_args();path=Path(a.out)
    rows=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else []
    if any(r['platform']==a.platform and r['tenant_id']==a.tenant and r['user_id']==a.user for r in rows):
        p.error('Matching platform principal already exists; edit or rotate its private credential explicitly')
    rows.append({'platform':a.platform,'mode':a.mode,'token':secrets.token_urlsafe(32),
        'tenant_id':a.tenant,'user_id':a.user,'groups':a.groups,'knowledge_ids':a.knowledge_ids})
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    try:path.chmod(0o600)
    except OSError:pass
    print('Platform credential saved in the private configuration file; token not printed.')


if __name__=='__main__':main()
