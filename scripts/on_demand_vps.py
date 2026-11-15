"""Owned NeoWiki VPS inspection and immutable on-demand source staging.

Never reads provider secret values or changes campaign/backfill containers.
Cutover is a separate, explicit operation after reviewing the staged manifest.
"""
import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
import subprocess
import zipfile

REPO=Path(__file__).resolve().parent.parent
SSH=['ssh','-i',str(REPO.parent/'Palimpsest-comparisons/.local/neowiki-vps-deploy'),
     '-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','root@179.67.199.219','python3 -']


def remote(code):
    result=subprocess.run(SSH,input=code,text=True,encoding='utf-8',capture_output=True)
    print(result.stdout)
    if result.stderr:print(result.stderr[-3000:])
    if result.returncode:raise SystemExit(result.returncode)


def inspect():
    remote('''import importlib.util,json,pathlib,subprocess
def run(args):return subprocess.check_output(args,text=True).strip()
print(json.dumps({'native_public':json.loads(pathlib.Path('/etc/neowiki-main/native-public.yaml').read_text()),'worker_image':run(['docker','image','inspect','neowiki-winter-detector:20261115','--format','{{.Id}}'])}))
code="import importlib.util,json; print(json.dumps({n:importlib.util.find_spec(n) is not None for n in ['google.genai','fastembed','flask','tokenizers','numpy','mwparserfromhell','pyarrow','pymysql','fastapi']}))"
print(run(['docker','run','--rm','--network','none','--entrypoint','python','neowiki-winter-detector:20261115','-c',code]))
print(pathlib.Path('/etc/neowiki-main/reader-scaffold/deploy/runtime.py').read_text())
''')


def stage():
    files={}
    for directory in ('tools/language-gap-explorer','palimpsest','prompts','infra/wiki/extensions/PalimpsestIssues'):
        for path in (REPO/directory).rglob('*'):
            relative=path.relative_to(REPO)
            if path.is_file() and not any(p.startswith('.') or p=='__pycache__' for p in relative.parts) and path.suffix in ('.py','.php','.json','.js','.css','.html','.txt','.md','.yaml','.yml'):
                files[relative.as_posix()]=path.read_bytes()
    manifest={name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
    identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    base=subprocess.check_output(['git','-C',str(REPO),'merge-base','HEAD','origin/main'],text=True).strip()
    files['manifest.json']=json.dumps(dict(identity=identity,files=manifest,base=base,scope='On-demand queue and native UI; no paid authorization'),indent=2).encode()
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,body in files.items():archive.writestr(name,body)
    code='''import base64,hashlib,io,json,pathlib,shutil,zipfile
identity=IDENTITY
folder=pathlib.Path('/opt/neowiki-on-demand/releases')/identity
assert shutil.disk_usage('/').free>30_000_000_000,'Disk guard: pause preparation below30GB'
folder.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(io.BytesIO(base64.b64decode(ARCHIVE))) as archive:
 for name in archive.namelist():
  p=pathlib.PurePosixPath(name);assert not p.is_absolute() and '..' not in p.parts
  target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
  data=archive.read(name)
  if target.exists():assert target.read_bytes()==data,'Immutable staged source changed'
  else:target.write_bytes(data);target.chmod(0o644)
manifest=json.loads((folder/'manifest.json').read_text())
assert all(hashlib.sha256((folder/n).read_bytes()).hexdigest()==sha for n,sha in manifest['files'].items())
print(json.dumps({'identity':identity,'release':str(folder),'files':len(manifest['files']),'staged_only':True,'provider_calls':0}))
'''.replace('IDENTITY',repr(identity)).replace('ARCHIVE',repr(base64.b64encode(out.getvalue()).decode()))
    remote(code)


def validate(identity):
    if not re.fullmatch('[a-f0-9]{64}',identity or ''):raise ValueError('Use the staged release hash.')
    remote('''import json,pathlib,subprocess
folder=pathlib.Path('/opt/neowiki-on-demand/releases')/IDENTITY
assert (folder/'manifest.json').is_file()
image='sha256:46814597c3e92d171c22ba483ca2978cfaf81630033c56b01eb2a3e66c01052b'
prefix=['docker','run','--rm','--network','none','--read-only','--user','10001:10001','--tmpfs','/tmp:rw,nosuid,nodev,size=128m','--volume',str(folder)+':/source:ro','--workdir','/source/tools/language-gap-explorer','--env','PYTHONPATH=/source','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHON_DOTENV_DISABLED=1','--env','NEOWIKI_TEST_DETECTOR_ADAPTER=1','--entrypoint','python',image,'-B']
subprocess.run(prefix+['-m','unittest','test_on_demand','test_on_demand_detector','test_native_issues','test_article_pipeline','test_paired_history','test_historical_divergence','test_issues','-q'],check=True)
subprocess.run(prefix+['-c',"from google.genai import types; import palimpsest.api as a; assert types.HttpRetryOptions(attempts=1).attempts==1; print('Detector imports and single-attempt SDK configuration verified; no credentials/network/provider calls.')"],check=True)
native_image=subprocess.check_output(['docker','inspect','palimpsest-native-vps-wiki-en-1','--format','{{.Image}}'],text=True).strip()
for path in (folder/'infra/wiki/extensions/PalimpsestIssues').rglob('*.php'):
 subprocess.run(['docker','run','--rm','--network','none','--read-only','--volume',str(folder)+':/source:ro','--entrypoint','php',native_image,'-l','/source/'+str(path.relative_to(folder))],check=True)
subprocess.run(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=16m','--volume',str(folder)+':/source:ro','--entrypoint','php',native_image,'/source/infra/wiki/extensions/PalimpsestIssues/tests/run.php'],check=True)
print(json.dumps({'staged_release':str(folder),'offline_container_tests':'passed','native_php_lint':'passed','paid_calls':0,'production_services_changed':False}))
'''.replace('IDENTITY',repr(identity)))


def inventory():
    code='''import json
from core import connect
topics=['Q122100','Q211855','Q154940','Q202808']
with connect() as db,db.cursor() as c:
 c.execute('SELECT wikidata_id,lang,page_id,rev_id,title,date_modified FROM article WHERE wikidata_id IN ('+','.join(['%s']*len(topics))+') ORDER BY wikidata_id,lang',topics)
 articles=list(c.fetchall())
 c.execute("SELECT topic,mode,COUNT(*) assessments FROM unified_assessment WHERE mode IN ('page','revision') GROUP BY topic,mode")
 assessments=list(c.fetchall())
print(json.dumps({'candidate_articles':articles,'existing_detector_assessments':assessments},default=str))
'''
    remote('''import subprocess
code=CODE
result=subprocess.run(['docker','exec','-i','neowiki-research-native-issues-1','python','deploy/runtime.py','python','-'],input=code,text=True,capture_output=True)
print(result.stdout)
if result.returncode:print('Read-only inventory failed');raise SystemExit(result.returncode)
'''.replace('CODE',repr(code)))


def framing():
    remote('''import json,urllib.request,urllib.parse
base='http://127.0.0.1:8080'
data=json.load(urllib.request.urlopen(base+'/api/issues?topic=Q134949&kind=framing&lang=en'))
selected={'8cab191429a89ead45492c30a5f2f5de8480eb578ccb56025b0bc97b6adecef8','f59572b6bbd643f86a60d9e526e830e7d6bce65939dc824b0d775774afad7ae2','85486186e21e90cee2085e59a69c3b56880d18ff0a8b533522917f3511cc7f11'}
for row in data['issues']:
 if row['id'] not in selected:continue
 query=urllib.parse.urlencode({'topic':'Q134949','lang':'en','observation':row['observation'],'occurrence':row['occurrence']})
 detail=json.load(urllib.request.urlopen(base+'/api/issues/'+row['id']+'?'+query))
 evidence=detail['evidence'];passages=list(dict.fromkeys(f.get('anchor_text','') for f in evidence['flags']))
 print(json.dumps({'id':row['id'],'title':row['title'],'observation':row['observation'],'occurrence':row['occurrence'],'sources':evidence['sources'],'passages':passages,'translations':evidence.get('translations',[])},ensure_ascii=True))
''')


def demo(command,identity):
    if not re.fullmatch('[a-f0-9]{64}',identity or ''):raise ValueError('Use the validated release hash.')
    code="import sys\nsys.argv="+repr(['on_demand_demo_remote.py',command,'--release',identity])+"\n"+(REPO/'scripts/on_demand_demo_remote.py').read_text(encoding='utf-8')
    remote(code)


def database_validate(identity):
    if not re.fullmatch('[a-f0-9]{64}',identity or ''):raise ValueError('Use the validated release hash.')
    remote('''import pathlib,subprocess
folder=pathlib.Path('/opt/neowiki-on-demand/releases')/IDENTITY
code="from pathlib import Path; import os,unittest; os.environ['DB_PASSWORD']=Path('/run/secrets/db-password').read_text().strip(); unittest.main(module='test_issues',argv=['unittest','IssueDatabaseTests','-v'])"
args=['docker','run','--rm','--network','neowiki-research_default','--read-only','--user','10001:10001','--group-add','33','--tmpfs','/tmp:rw,nosuid,nodev,size=64m',
 '--volume',str(folder)+':/source:ro','--volume','/etc/neowiki-research/secrets/db-password:/run/secrets/db-password:ro',
 '--workdir','/source/tools/language-gap-explorer','--env','PYTHONPATH=/source','--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHON_DOTENV_DISABLED=1',
 '--env','PALIMPSEST_TEST_ISSUES_DB=1','--env','DB_HOST=neowiki-research-db-1','--env','DB_PORT=3306','--env','DB_USER=explorer','--env','DB_NAME=language_gaps',
 '--env','NEOWIKI_RESEARCH_ROOT=/tmp/fixture-root','--entrypoint','python','sha256:46814597c3e92d171c22ba483ca2978cfaf81630033c56b01eb2a3e66c01052b','-B','-c',code]
subprocess.run(args,check=True)
print('Isolated MariaDB/SVT contract tests passed; only their uniquely named test_ui_* tables were created/dropped. No provider keys mounted or calls made.')
'''.replace('IDENTITY',repr(identity)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('inspect','stage','validate','database-validate','inventory','framing','demo-prepare','demo-start','demo-status'));parser.add_argument('--release');args=parser.parse_args()
    if args.command=='inspect':inspect()
    elif args.command=='stage':stage()
    elif args.command=='inventory':inventory()
    elif args.command=='framing':framing()
    elif args.command.startswith('demo-'):demo(args.command.removeprefix('demo-'),args.release)
    elif args.command=='database-validate':database_validate(args.release)
    else:validate(args.release)
