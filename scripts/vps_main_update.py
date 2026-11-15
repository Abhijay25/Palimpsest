"""Update this owned VPS from main without touching datasets or running workers.

Operator paths/configuration live in /etc/neowiki-main/config.json. Run from a
systemd oneshot/timer; a lock prevents overlapping builds. Releases are retained.
"""
from pathlib import Path
import argparse,fcntl,json,os,re,shutil,subprocess,time,urllib.request


def command(args, **kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    config=json.loads(Path('/etc/neowiki-main/config.json').read_text())
    lock=Path('/run/lock/neowiki-main-update.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    repo=Path(config['repository'])
    command(['git','-C',repo,'fetch','origin','refs/heads/main:refs/remotes/origin/main'])
    revision=subprocess.check_output(['git','-C',repo,'rev-parse','refs/remotes/origin/main'],text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}',revision):raise RuntimeError('Invalid main revision')
    state_file=Path('/var/lib/neowiki-main/state.json')
    previous=json.loads(state_file.read_text()) if state_file.exists() else {}
    if previous.get('revision')==revision and not args.force:return
    release=Path('/opt/neowiki-research/releases')/revision
    if not release.exists():
        release.mkdir(parents=True)
        archive=command(['git','-C',repo,'archive',revision],stdout=subprocess.PIPE).stdout
        command(['tar','-x','-C',release],input=archive)
    app=release/'tools/language-gap-explorer';glue=Path(config['reader_scaffold'])
    # Existing operator-reviewed packaging stays available until it lands in main.
    for name in ['Dockerfile','.dockerignore','requirements.docker.txt','deploy']:
        if not (app/name).exists():
            if (glue/name).is_dir():shutil.copytree(glue/name,app/name)
            else:shutil.copyfile(glue/name,app/name)
    wsgi=app/'deploy/wsgi.py';text=wsgi.read_text()
    if "'issues.native_target'" not in text:
        text=text.replace("'discrepancy_explorer.heatmap_cell',","'discrepancy_explorer.heatmap_cell', 'issues.native_target', 'issues.index', 'issues.detail', 'issues.list_api', 'issues.detail_api',")
        wsgi.write_text(text)
    tag='main-'+revision[:12];image='neowiki-research:'+tag
    command(['docker','build','--tag',image,app])
    command(['docker','run','--rm','--network','none','--entrypoint','python',image,'-B','-m','unittest','test_native_issues','-q'])
    Path('/var/lib/neowiki-main').mkdir(parents=True,exist_ok=True)
    Path('/var/lib/neowiki-main/prepared.json').write_text(json.dumps(dict(revision=revision,image=image,release=str(release)))+'\n')
    if args.prepare_only:return
    env=os.environ.copy();env['NEOWIKI_IMAGE_TAG']=tag
    services=['web','native-issues']
    compose=['docker','compose','--project-name','neowiki-research','--env-file',config['environment']]
    for name in config['compose_files']:compose+=['-f',name]
    compose+=['-f','/etc/neowiki-main/bridge.yaml']
    on_demand=config.get('on_demand')
    if on_demand:
        # Opt-in operator configuration; campaign workers and their mounts/keys
        # remain unchanged. Source follows the same verified main release.
        profile=app/'compose.on-demand.yaml'
        if not profile.is_file():raise RuntimeError('On-demand profile is absent from this release')
        for key in ('root','policy_file','image'):
            if not on_demand.get(key):raise RuntimeError('Incomplete on-demand runtime configuration')
        env.update(NEOWIKI_SOURCE_RELEASE=str(release),NEOWIKI_ON_DEMAND_ROOT=on_demand['root'],
            NEOWIKI_ON_DEMAND_POLICY=on_demand['policy_file'],NEOWIKI_ON_DEMAND_IMAGE=on_demand['image'])
        compose+=['-f',str(profile)]
        # An optional, separately reviewed credential mount overlay is never
        # inferred from a historical campaign's key or authorization.
        if on_demand.get('credential_overlay'):compose+=['-f',on_demand['credential_overlay']]
        services.append('on-demand-worker')
    native=Path(config['native_repository'])
    native_previous=subprocess.check_output(['git','-C',native,'rev-parse','HEAD'],text=True).strip()
    native_prefix=None;native_env=None
    try:
        command(compose+['up','-d','--no-deps',*services],env=env)
        for attempt in range(24):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=5) as response:
                    if response.status==200:break
            except OSError:time.sleep(3)
        else:raise RuntimeError('Reader health check failed')
        # The native checkout is separate from the old worker's checkout.
        if subprocess.check_output(['git','-C',native,'status','--porcelain'],text=True).strip():raise RuntimeError('Native checkout has local changes; preserved them')
        command(['git','-C',native,'checkout','--detach',revision])
        import sys
        sys.path.insert(0,str(native));from scripts import runtime
        native_data=Path(config['native_data']);docker,native_env=runtime.resolve_docker();native_env.update(runtime.native_profile(native_data)['environment'])
        for language in ['fi','sv','en']:
            shutil.copyfile(native/'infra/wiki/runtime-settings.php',native_data/'config'/language/'runtime-settings.php')
        prefix=runtime.compose_prefix(docker,native_data/'.env')+['-f','/etc/neowiki-main/native-public.yaml']
        native_prefix=prefix
        command(prefix+['up','-d','--no-deps','--force-recreate','wiki-fi','wiki-sv','wiki-en','jobs-fi','jobs-sv','jobs-en'],env=native_env)
        for port in [18091,18092,18093]:
            for attempt in range(24):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/api.php?action=query&meta=siteinfo&format=json',timeout=5) as response:
                        if 'query' in json.load(response):break
                except OSError:time.sleep(3)
            else:raise RuntimeError('Native wiki health check failed')
    except Exception:
        if native_prefix is not None:
            command(['git','-C',native,'checkout','--detach',native_previous])
            for language in ['fi','sv','en']:
                shutil.copyfile(native/'infra/wiki/runtime-settings.php',native_data/'config'/language/'runtime-settings.php')
            command(native_prefix+['up','-d','--no-deps','--force-recreate','wiki-fi','wiki-sv','wiki-en','jobs-fi','jobs-sv','jobs-en'],env=native_env)
        if previous.get('image'):
            rollback=env.copy();rollback['NEOWIKI_IMAGE_TAG']=previous['image'].split(':',1)[1]
            rollback_compose=compose
            if on_demand:
                previous_release=Path('/opt/neowiki-research/releases')/previous['revision']
                previous_profile=previous_release/'tools/language-gap-explorer/compose.on-demand.yaml'
                rollback['NEOWIKI_SOURCE_RELEASE']=str(previous_release)
                if previous_profile.is_file():
                    rollback_compose=[str(previous_profile) if part==str(profile) else part for part in compose]
                else:
                    # First queue rollout failed: restore the prior cached-only
                    # bridge and preserve, but stop, only this newly owned worker.
                    command(compose+['stop','on-demand-worker'],env=env)
                    rollback_compose=compose[:compose.index(str(profile))-1]
            command(rollback_compose+['up','-d','--no-deps',*(services if on_demand and previous_profile.is_file() else ['web','native-issues'])],env=rollback)
        raise
    state_file.write_text(json.dumps(dict(revision=revision,image=image,release=str(release),deployed_at=time.time()),indent=2)+'\n')
    print('Deployed main '+revision,flush=True)


if __name__=='__main__':main()
