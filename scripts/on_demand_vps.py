"""Owned NeoWiki VPS inspection and immutable on-demand source staging.

Never reads provider secret values or changes campaign/backfill containers.
Cutover is a separate, explicit operation after reviewing the staged manifest.
"""
import argparse
import base64
import hashlib
import io
import json
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
            if path.is_file() and not any(p.startswith('.') or p=='__pycache__' for p in relative.parts) and path.suffix in ('.py','.php','.json','.js','.css','.html','.txt','.md'):
                files[relative.as_posix()]=path.read_bytes()
    manifest={name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
    identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    files['manifest.json']=json.dumps(dict(identity=identity,files=manifest,base='747725b8b0e041e24abc02117e0b96daec63438e',scope='On-demand queue and native UI; no paid authorization'),indent=2).encode()
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


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('inspect','stage'));args=parser.parse_args()
    inspect() if args.command=='inspect' else stage()
