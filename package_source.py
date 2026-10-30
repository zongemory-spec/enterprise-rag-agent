"""Build a source-only archive with a checksum manifest and a single root folder."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FOLDER = 'enterprise-rag-agent-v4.2'


def source_files(root):
    files = set()
    for pattern in ('*.py', '*.md', '*.txt', '*.lock', '*.ps1', '*.yaml', '*.yml'):
        files.update(root.glob(pattern))
    for name in ('.env.example', '.gitignore', '.dockerignore', '.gitattributes', 'Dockerfile', 'SOURCE_BASELINE.json', 'evaluation_gate.json'):
        path = root / name
        if path.is_file():
            files.add(path)
    for directory, suffixes in {
        'rag_app': {'.py', '.html'}, 'tests': {'.py'},
        'docs': {'.md'}, 'reports': {'.md', '.json'},
        'data/synthetic': {'.md', '.json'}, 'data/showcase': {'.md'}, '.github': {'.yml', '.yaml'},
        'integrations': {'.json','.yaml','.yml','.md'},
    }.items():
        files.update(p for p in (root / directory).rglob('*') if p.is_file() and p.suffix in suffixes
                     and '__pycache__' not in p.parts)
    files={p for p in files if 'integrations' not in p.relative_to(root).parts or p.name in {'openapi.json','openapi.yaml','WORKFLOW.md','platform_auth.example.json'}}
    files.add(root / 'data/questions.json')
    return sorted(p for p in files if p.is_file())


def build_archive(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new output path; existing archives are preserved')
    output.parent.mkdir(parents=True, exist_ok=True)
    files = source_files(root)
    manifest = {'version': '4.2', 'root': FOLDER, 'files': [
        {'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
         'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, FOLDER + '/' + path.relative_to(root).as_posix())
        archive.writestr(FOLDER + '/PACKAGE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    return {'archive': str(output), 'source_files': len(files),
            'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='dist/enterprise-rag-agent-v4.2-source.zip')
    args = parser.parse_args()
    print(json.dumps(build_archive(ROOT, args.out), ensure_ascii=False, indent=2))
