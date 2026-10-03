from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parent
FILES=["README.md","requirements.txt","requirements.lock","seed_data.py","init_demo.py","evaluate.py","sync_pg.py","run_server.py","migrate_sqlite.py",
       "package_source.py","verify_real_agent.py","start.ps1",".env.example",".gitignore",".dockerignore","Dockerfile","compose.yaml",
       "compose.pg.yaml",".github/workflows/tests.yml","data/questions.json","data/synthetic/manifest.json"]
if __name__=="__main__":
    out=ROOT/"dist"/"enterprise-rag-v3_2.zip";out.parent.mkdir(exist_ok=True)
    paths=[ROOT/f for f in FILES]
    for pattern in ["rag_app/*.py","rag_app/*.html","tests/test_*.py","data/synthetic/*.md","docs/*.md","reports/*.md","reports/*.json"]:
        paths+=list(ROOT.glob(pattern))
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(paths)):z.write(path,path.relative_to(ROOT))
    print("Created source-only archive:",out.name)

