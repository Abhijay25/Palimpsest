"""Explicit bounded capture of public Wikidata rendering dependencies. No inference."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.palimpsest_data.history import fetch_json,utc_now
from scripts.palimpsest_data.io import atomic_json

ENTITY=re.compile(r'^[QP][1-9][0-9]*$')

def references(entity):
    found=set()
    def walk(value,key=''):
        if isinstance(value,dict):
            for name,item in value.items():
                if ENTITY.fullmatch(name):found.add(name)
                walk(item,name)
        elif isinstance(value,list):
            for item in value:walk(item,key)
        elif isinstance(value,str):
            if key in ('id','property') and ENTITY.fullmatch(value):found.add(value)
            if key in ('unit','calendarmodel') and value.startswith('http://www.wikidata.org/entity/'):
                candidate=value.rsplit('/',1)[-1]
                if ENTITY.fullmatch(candidate):found.add(candidate)
    walk(entity)
    found.discard(entity['id'])
    return found


def capture(output,roots,limit=150,linked=False,api=fetch_json):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True);path=output/'manifest.json'
    manifest=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(schema_version=1,source_wiki='wikidatawiki',entities={})
    if manifest.get('schema_version')!=1 or manifest.get('source_wiki')!='wikidatawiki':raise ValueError('Source capture identity mismatch.')
    for identity,record in manifest['entities'].items():
        if not ENTITY.fullmatch(identity):raise ValueError('Invalid captured entity identity.')
        raw=(output/(identity+'.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('Existing captured source changed.')
        entity=json.loads(raw)
        if entity['id']!=identity or entity['lastrevid']!=record['source_revision']:raise ValueError('Existing captured source identity changed.')
    wanted=set(roots)
    expanded=False
    while True:
        missing=sorted(wanted-set(manifest['entities']))
        if not missing:
            if linked and not expanded:
                for identity in roots:wanted.update(references(json.loads((output/(identity+'.json')).read_text(encoding='utf-8'))))
                expanded=True
                continue
            break
        if len(manifest['entities'])>=limit:break
        batch=missing[:min(20,limit-len(manifest['entities']))]
        manifest.update(roots=roots,linked_depth=int(linked),pending=missing,complete=False)
        atomic_json(path,manifest)
        data=api('https://www.wikidata.org/w/api.php?'+urlencode(dict(action='wbgetentities',ids='|'.join(batch),props='info|labels|descriptions|aliases|claims|sitelinks|datatype',format='json',formatversion=2,maxlag=5)),retries=2)
        for identity in batch:
            entity=data.get('entities',{}).get(identity)
            if not entity or entity.get('id')!=identity or 'missing' in entity or not isinstance(entity.get('lastrevid'),int) or entity['lastrevid']<=0:
                raise ValueError('Exact source entity unavailable: '+identity)
            target=output/(identity+'.json')
            if target.exists() and identity not in manifest['entities']:raise ValueError('Unregistered source capture already exists; inspect it before importing.')
            atomic_json(target,entity)
            manifest['entities'][identity]=dict(sha256=hashlib.sha256(target.read_bytes()).hexdigest(),source_revision=entity['lastrevid'],modified=entity.get('modified'),source_url='https://www.wikidata.org/w/index.php?title='+identity+'&oldid='+str(entity['lastrevid']),acquired_at=utc_now())
            manifest.update(roots=roots,pending=sorted(wanted-set(manifest['entities'])),complete=False)
            atomic_json(path,manifest)
    manifest.update(roots=roots,pending=sorted(wanted-set(manifest['entities'])),complete=not bool(wanted-set(manifest['entities'])))
    atomic_json(path,manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--id',action='append',required=True)
    parser.add_argument('--linked',action='store_true',help='Capture one hop of actually referenced entities/properties.')
    parser.add_argument('--max-entities',type=int,default=150)
    args=parser.parse_args()
    if not all(ENTITY.fullmatch(value) for value in args.id) or not 1<=args.max_entities<=500:parser.error('Choose exact Q/P identities and a 1–500 entity bound.')
    try:
        result=capture(args.output,sorted(set(args.id)),args.max_entities,args.linked)
        print(json.dumps(dict(captured=len(result['entities']),pending=len(result['pending']),complete=result['complete'])))
        return 0 if result['complete'] else 1
    except Exception as error:
        print('Source capture incomplete; acquired entities are preserved: '+str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
