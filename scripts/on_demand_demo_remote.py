"""VPS-side reviewed operator for the explicitly approved four-article batch.

Invoked over SSH by on_demand_vps.py; no secret values are printed or returned.
It only creates its own policy/queue/worker and reads native/research sources.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

IMAGE='sha256:46814597c3e92d171c22ba483ca2978cfaf81630033c56b01eb2a3e66c01052b'
NAME='neowiki-demo-detector-four-20261115'
DATA=Path('/srv/neowiki-on-demand/demo-four-20261115')
POLICY=Path('/etc/neowiki-on-demand/demo-four-20261115.json')
AUTH='demo-four-20261115-100-gemini'
ANCHORS={'Q122100':{'en':1304070619,'fi':23388335,'sv':57639824},'Q211855':{'en':1307003624,'fi':23498098,'sv':57158733},'Q154940':{'en':1303461171,'fi':23340989,'sv':56730588},'Q202808':{'en':1287977631,'fi':23422349,'sv':57526430}}


def run(args,**kwargs):return subprocess.run([str(a) for a in args],check=True,**kwargs)


def policy():
    engine=dict(provider='gemini',model='gemini-4-hydrogen',reviewer_model='gemini-4-argon',triage_model='gemini-decision-1',prompt_version='stage2_v10',policy_version='native-demo-four-v1',max_output_tokens=8192)
    allowlist={lang:[r[lang] for r in ANCHORS.values()] for lang in ('en','fi','sv')}
    return dict(version=1,enabled=True,authorization_id=AUTH,policy_version='demo-four-v1',
        authorization='User explicitly approved four named demo articles,12 EN/FI/SV snapshots and12 exact preceding edits; maximum100Gemini provider calls total, no dollar ceiling. Winter War and paused OpenAI campaign are separate.',
        max_provider_calls=100,max_jobs=24,allow_operator_batch=True,
        engines={kind:dict(enabled=True,topics=list(ANCHORS),authorization=AUTH,max_provider_calls=100,allow_rescan=False,source_allowlist=allowlist,configuration=engine) for kind in ('page','revision')})


def scopes():
    output={}
    for lang in ('en','fi','sv'):
        php="$c=\\MediaWiki\\MediaWikiServices::getInstance()->getMainConfig();$id=(string)$c->get('PalimpsestIssuesWikiId');if($id===''){$id=hash('sha256',$c->get('Server').'|'.$c->get('DBname').'|'.$c->get('DBprefix'));}echo 'NEOWIKI_SCOPE:'.$id.PHP_EOL;\n"
        result=run(['docker','exec','-i','palimpsest-native-vps-wiki-'+lang+'-1','php','maintenance/run.php','eval'],input=php,text=True,capture_output=True)
        found=re.findall(r'NEOWIKI_SCOPE:([A-Za-z0-9_.:-]{1,100})',result.stdout)
        if len(found)!=1:raise RuntimeError('Could not read the actual native wiki scope.')
        output[lang]=found[0]
    return output


def base(release):
    assert shutil.disk_usage(DATA).free>30_000_000_000,'Disk preparation pause below30GB'
    env=dict(PYTHONPATH='/source',PYTHONDONTWRITEBYTECODE='1',PYTHON_DOTENV_DISABLED='1',
             NEOWIKI_RESEARCH_ROOT='/var/lib/neowiki',NEOWIKI_ON_DEMAND_ROOT='/var/lib/neowiki-on-demand',NEOWIKI_ON_DEMAND_POLICY='/run/on-demand-policy.json',
             DB_HOST='neowiki-research-db-1',DB_PORT='3306',DB_USER='explorer',DB_NAME='language_gaps',DB_PASSWORD_FILE='/run/secrets/db-password',
             LANGGAP_FLAGS_CACHE='/var/lib/neowiki/data/flags-cache',PLAYWRIGHT_BROWSERS_PATH='/ms-playwright')
    args=['--read-only','--user','10001:10001','--group-add','33','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','2g','--cpus','2','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--workdir','/source/tools/language-gap-explorer']
    mounts={release:'/source:ro',DATA:'/var/lib/neowiki-on-demand:rw',POLICY:'/run/on-demand-policy.json:ro',
            Path('/etc/neowiki-research/secrets/db-password'):'/run/secrets/db-password:ro',
            Path('/srv/neowiki-research/data'):'/var/lib/neowiki/data:ro',Path('/srv/neowiki-research/model-cache'):'/var/lib/neowiki/model-cache:ro'}
    for source,target in mounts.items():args+=['--volume',str(source)+':'+target]
    for key,value in env.items():args+=['--env',key+'='+value]
    return args


def ephemeral(release,role,commands,extra=None,native=False):
    name='neowiki-demo-tool-'+uuid.uuid4().hex[:12]
    args=['docker','create','--rm','--name',name,'--network','neowiki-research_default',*base(release),*(extra or []),'--entrypoint','python',IMAGE,'on_demand_runtime.py',role,*commands]
    run(args,stdout=subprocess.DEVNULL)
    if native:run(['docker','network','connect','palimpsest-native-vps-wiki',name])
    run(['docker','start','--attach',name])


def prepare(release):
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700);os.chown(DATA,10001,10001)
    POLICY.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(policy(),sort_keys=True,ensure_ascii=False,indent=2)+'\n'
    if POLICY.exists():assert POLICY.read_text()==encoded,'Existing authorization preserved; inspect differences instead of replacing it'
    else:POLICY.write_text(encoded);POLICY.chmod(0o644)
    provenance=DATA.parent/'provenance-demo-four';provenance.mkdir(exist_ok=True)
    for lang in ('en','fi','sv'):
        target=provenance/lang/(lang+'.json');target.parent.mkdir(exist_ok=True)
        source=Path('/srv/neowiki-native/wiki/config')/lang/(lang+'.json')
        target.write_bytes(source.read_bytes());target.chmod(0o444)
    native_scopes=scopes()
    (DATA/'native-scopes.json').write_text(json.dumps(native_scopes));os.chown(DATA/'native-scopes.json',10001,10001)
    ephemeral(release,'init',[])
    apis={lang:'http://wiki-'+lang+'/api.php' for lang in ('en','fi','sv')}
    extra=['--volume',str(provenance)+':/native-provenance:ro','--env','NEOWIKI_NATIVE_PROVENANCE=/native-provenance','--env','NEOWIKI_NATIVE_SCOPES='+json.dumps(native_scopes),'--env','NEOWIKI_NATIVE_APIS='+json.dumps(apis)]
    ephemeral(release,'batch',['prepare'],extra,native=True)


def start(release):
    # Exact repeats are readbacks, never duplicate containers or paid replays.
    existing=subprocess.run(['docker','inspect',NAME],capture_output=True,text=True)
    if existing.returncode==0:
        print(json.dumps({'worker_exists':True,'status':json.loads(existing.stdout)[0]['State']['Status']}));return
    assert POLICY.is_file() and json.loads(POLICY.read_text())==policy(),'The approved batch policy changed'
    ephemeral(release,'batch',['enqueue'])
    values={}
    for line in Path('/etc/neowiki-native/detector.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1)
            if key.strip()=='GEMINI_API_KEY':values[key.strip()]=value.strip().strip('"\'')
    value=values.get('GEMINI_API_KEY');assert value and '\n' not in value,'Approved Gemini credential is unavailable'
    secret=POLICY.parent/'demo-four-gemini-key'
    if secret.exists():assert secret.read_text()==value,'Existing private credential differs; preserved it'
    else:
        descriptor=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
        with os.fdopen(descriptor,'w') as stream:stream.write(value)
        os.chown(secret,10001,10001)
    del value,values
    args=['docker','run','-d','--restart','unless-stopped','--name',NAME,'--network','neowiki-research_default','--init',*base(release),
          '--volume',str(secret)+':/run/secrets/gemini-key:ro','--env','GEMINI_API_KEY_FILE=/run/secrets/gemini-key','--entrypoint','python',IMAGE,'on_demand_runtime.py','worker']
    run(args,stdout=subprocess.DEVNULL)
    print(json.dumps({'worker':NAME,'started':True,'max_provider_calls_total':100,'max_jobs':24,'openai_key_mounted':False,'winter_worker_changed':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','start','status'));parser.add_argument('--release',required=True);args=parser.parse_args()
    assert re.fullmatch('[a-f0-9]{64}',args.release)
    release=Path('/opt/neowiki-on-demand/releases')/args.release
    manifest=json.loads((release/'manifest.json').read_text())
    assert all(hashlib.sha256((release/n).read_bytes()).hexdigest()==sha for n,sha in manifest['files'].items())
    if args.command=='prepare':prepare(release)
    elif args.command=='start':start(release)
    else:ephemeral(release,'batch',['status'])
