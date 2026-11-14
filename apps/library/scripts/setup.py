#!/usr/bin/env python3
"""Reproduce the isolated Library runtime and real curated corpus; never reset data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'apps/library'
DATA = ROOT / '.local/library'
WIKI = DATA / 'wiki'
DOCKER = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'
ENV = {**os.environ, 'PATH': str(Path(DOCKER).parent) + os.pathsep + os.environ.get('PATH', '')}
COMMON = ['--project', 'palimpsest-library', '--data-root', str(WIKI), '--ports', '48181,48182,48183']

def run(command, label, *, optional=False):
    print(label, flush=True)
    with (DATA / f'{label}.log').open('a') as log:
        result = subprocess.run(command, cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode and not optional:
        raise RuntimeError(f'{label} failed ({result.returncode}); see {DATA / (label + ".log")}')
    return result.returncode

def wiki(*arguments, label, optional=False):
    return run([sys.executable, 'scripts/wiki', *COMMON, *arguments], label, optional=optional)

def configure():
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ('database-password', 'database-root-password'):
        path = DATA / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32))
            path.chmod(0o600)
    images = json.loads((ROOT / 'infra/wiki/images.lock.json').read_text())['images']['mariadb']
    env_path = DATA / 'database.env'
    env_path.write_text(f'LIBRARY_DATA_ROOT={DATA}\nLIBRARY_MARIADB_IMAGE={images["reference"]}@{images["digest"]}\n')
    config = {'dataRoot': str(DATA), 'database': {'host': '127.0.0.1', 'port': 48184, 'database': 'library', 'user': 'library', 'password': (DATA / 'database-password').read_text()}, 'ollama': 'http://127.0.0.1:11435', 'model': 'bge-m3', 'wikis': {lang: f'http://127.0.0.1:{port}' for lang, port in [('fi',48181),('sv',48182),('en',48183)]}}
    config_path = DATA / 'config.json'
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    config_path.chmod(0o600)

def extract():
    assets = ROOT / '.local/wiki/dataset/raw'
    if not assets.exists():
        raise RuntimeError('Locked S assets are missing. Run python3 scripts/wiki dataset fetch first.')
    run([DOCKER, 'run', '--rm', '--network', 'none', '--entrypoint', 'python', '-v', f'{ROOT}:/repo:ro', '-v', f'{assets}:/data:ro', '-v', f'{DATA}:/out', 'palimpsest-data-tooling:s-2026-10', '/repo/apps/library/scripts/extract.py', '--assets', '/data', '--lock', '/repo/datasets.lock.json', '--output', '/out/catalog.json'], 'extract')

def embedding_service():
    url = 'http://127.0.0.1:11435/api/tags'
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            json.load(response)
    except OSError:
        ollama = shutil.which('ollama')
        if not ollama:
            raise RuntimeError('Install Ollama, or start a compatible service on 127.0.0.1:11435.')
        env = {**ENV, 'OLLAMA_HOST':'127.0.0.1:11435', 'OLLAMA_MODELS':str(DATA / 'ollama')}
        with (DATA / 'ollama.log').open('a') as log:
            child = subprocess.Popen([ollama, 'serve'], env=env, stdout=log, stderr=subprocess.STDOUT)
        (DATA / 'ollama.pid').write_text(str(child.pid))
        for _ in range(30):
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    json.load(response)
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Ollama did not become ready; inspect the feature-owned log.')
    req = urllib.request.Request('http://127.0.0.1:11435/api/pull', data=json.dumps({'model':'bge-m3', 'stream':False}).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=900) as response:
        result = json.load(response)
    if result.get('status') != 'success':
        raise RuntimeError(f'Embedding model preparation failed: {result}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['all','runtime','extract','histories','support','import','provenance','vectors','model'], default='all')
    args = parser.parse_args()
    configure()
    phases = ['runtime','extract','histories','support','import','provenance','vectors','model'] if args.phase == 'all' else [args.phase]
    for phase in phases:
        if phase == 'runtime':
            wiki('setup', label='runtime')
        elif phase == 'extract':
            extract()
        elif phase == 'histories':
            wiki('history','acquire','--sample-manifest','apps/library/corpus.json','--interval','1',label='histories')
        elif phase == 'support':
            wiki('history','probe-anchors','--sample-manifest','apps/library/corpus.json',label='anchors')
            code = wiki('data','support','--sample-manifest','apps/library/corpus.json','--max-requests','60','--max-pages-per-root','100',label='support',optional=True)
            if code:
                print('Supporting rendering closure remains incomplete; preserved in the report, independently of article history.')
        elif phase == 'import':
            wiki('data','import','--sample-manifest','apps/library/corpus.json',label='import',optional=True)
            wiki('verify','--scope','sample','--sample-manifest','apps/library/corpus.json',label='coverage')
        elif phase == 'provenance':
            run([sys.executable,'scripts/blame_provenance.py','--data-root',str(WIKI),'--manifest','apps/library/corpus.json','--install'], 'provenance')
        elif phase == 'vectors':
            run([DOCKER,'compose','--project-name','palimpsest-library-vector','--env-file',str(DATA/'database.env'),'-f','apps/library/compose.yaml','up','-d','--wait'], 'database')
            run(['node','apps/library/scripts/load-catalog.mjs'], 'catalog-load')
        elif phase == 'model':
            embedding_service()
    print('Completed requested setup phases. No data was reset.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Library setup: {error}', file=sys.stderr)
        raise SystemExit(1)
