"""Store private references, not copied credentials."""
import json
from pathlib import Path
if __name__=='__main__':
    database=r'D:\PostgreSQL\config\connection.json'
    provider=r'D:\desktop\Agent Security Mini Lab\agent_security_real_api_lab_v2_1\.env'
    if not Path(database).is_file() or not Path(provider).is_file():raise SystemExit('Configuration reference missing.')
    path=Path(__file__).resolve().parent/'data/local_config.json'
    if path.exists():raise SystemExit('Private config exists; left unchanged.')
    path.write_text(json.dumps({'postgres_config':database,'postgres_schema':'rag_v3_3_semantic','provider_env_file':provider},indent=2),encoding='utf-8')
    print('Created private references for isolated v3.3 schema; no secrets copied or printed.')
