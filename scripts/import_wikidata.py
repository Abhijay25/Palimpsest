"""Import captured rendering data through the official store on an explicitly owned runtime."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.palimpsest_data.io import atomic_json
from scripts.palimpsest_data.history import ensure_free_space

ROOT=Path(__file__).resolve().parents[1]


def run(data_root,project,languages,wikibase_root):
    data_root=data_root.resolve();runtime=json.loads((data_root/'runtime.json').read_text(encoding='utf-8'))
    if runtime['project']!=project or Path(runtime['data_root']).resolve()!=data_root or not all(runtime['initialized'].values()):raise ValueError('Explicit runtime ownership/initialization mismatch.')
    ensure_free_space(data_root,2*1024**3)
    pin=json.loads((ROOT/'infra/wiki/extensions/rendering.lock.json').read_text(encoding='utf-8'))['wikibase']
    prepared=json.loads((wikibase_root/'.palimpsest-rendering.json').read_text(encoding='utf-8'))
    if prepared.get('commit')!=pin['commit'] or prepared.get('archive_sha256')!=pin['sha256']:raise ValueError('Prepared rendering package does not match the pin.')
    manifest=json.loads((data_root/'imports/wikidata/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('source_wiki')!='wikidatawiki':raise ValueError('Source capture identity mismatch.')
    env=dict(os.environ,PALIMPSEST_WIKIBASE_ROOT=str(wikibase_root.resolve()))
    command=['docker','compose','--project-directory',str(ROOT),'--env-file',str(data_root/'.env'),'-f',str(ROOT/'infra/wiki/compose.yaml'),'-f',str(ROOT/'infra/wiki/compose.rendering.override.yaml'),'run','--rm','--no-deps']
    for language in languages:
        result=subprocess.run([*command,'wiki-'+language,'php','maintenance/run.php','/opt/palimpsest/extensions/maintenance/import-wikidata.php','--manifest','/data/imports/wikidata/manifest.json'],cwd=ROOT,env=env,capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Native source-data import incomplete; prior entities preserved. '+(result.stderr or result.stdout)[-1500:])
        report=None
        for line in reversed(result.stdout.splitlines()):
            try:report=json.loads(line)
            except ValueError:continue
            if isinstance(report,dict) and report.get('source_wiki')=='wikidatawiki' and isinstance(report.get('entities'),list):break
        if not report or {r['id'] for r in report['entities']}!=set(manifest['entities']):raise ValueError('Native import did not report all captured source entities.')
        atomic_json(data_root/'issue-wikidata'/(language+'-mapping.json'),report)
        print(language+': '+str(len(report['entities']))+' source entities reconciled; source/local revisions saved separately.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True);parser.add_argument('--project',required=True)
    parser.add_argument('--language',choices=['en','fi','sv'],action='append',required=True)
    parser.add_argument('--wikibase-root',type=Path,default=ROOT/'.local/wb')
    args=parser.parse_args();run(args.data_root,args.project,list(dict.fromkeys(args.language)),args.wikibase_root)

if __name__=='__main__':main()
