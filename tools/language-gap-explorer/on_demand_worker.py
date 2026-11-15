"""Owned worker: python on_demand_worker.py init|work|run-one <job-id>.

One isolated child executes a job. Parent restart never resubmits uncertain work.
No key is accepted in a command argument, browser request or queue record.
"""
import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import on_demand_jobs as jobs


class DiskPause(RuntimeError):
    pass


def disk():
    if shutil.disk_usage(jobs.root()).free < 30_000_000_000:
        raise DiskPause('Preparation paused below 30 GB free disk space.')


def serial(value):
    if isinstance(value, type) and hasattr(value, 'model_json_schema'):
        return value.model_json_schema()
    if hasattr(value, 'model_dump'):
        return serial(value.model_dump(mode='python', exclude_none=True))
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def raw_path(identity):
    return jobs.root() / 'results' / (identity + '.json')


def archive(job, result):
    folder = jobs.root() / 'results'
    folder.mkdir(exist_ok=True, mode=0o700)
    path = raw_path(job['id'])
    if path.exists():
        raise RuntimeError('A result already exists; index it without rerunning the provider.')
    temporary = path.with_suffix('.part')
    with temporary.open('x', encoding='utf-8') as stream:
        stream.write(jobs.packed(dict(job=job['id'],configuration=job['config'],result=result)))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return result


def load_result(job):
    packet = json.loads(raw_path(job['id']).read_text(encoding='utf-8'))
    if packet['job'] != job['id'] or packet['configuration'] != job['config']:
        raise ValueError('Archived result identity mismatch.')
    return packet['result']


def compatible_scan(job):
    if job['kind']=='language' or job.get('previous'):return None
    from core import connect
    source=job['sources'][0]
    with connect() as db,db.cursor() as c:
        c.execute('SELECT payload FROM unified_assessment WHERE topic=%s AND mode=%s ORDER BY assessed_at DESC,id DESC',(job['topic'],job['kind']))
        for row in c.fetchall():
            packet=json.loads(row['payload']);value=packet.get('result',{})
            old=value.get('on_demand_configuration')
            if not old:continue  # unversioned legacy results are readable, not declared compatible
            normalize=lambda cfg:{k:v for k,v in cfg.items() if k not in ('authorization','authorization_id')}
            if normalize(old)==normalize(job['config']) and value.get('status')=='ok' and value.get('source_sha256')==source['sha256'] and value.get('parent_sha256')==source.get('parent_sha256'):
                return dict(value,reused_assessment=packet.get('result',{}).get('_issue_assessment'))
    return None


def attempts(job):
    with jobs.database() as db:
        rows = db.execute('SELECT status,response FROM attempt WHERE job=?', (job['id'],)).fetchall()
    return dict(calls=len(rows), failed_or_unknown=sum(r['status'] != 'done' for r in rows),
                usage=[json.loads(r['response']).get('usage_metadata', json.loads(r['response']).get('usage', {}))
                       for r in rows if r['response']])


def progress(job, stage, **details):
    jobs.update(job['id'], 'running', dict(stage=stage, **details))


async def detector(job):
    from on_demand_bridge import implementation_identity
    config = job['config']
    engine = config['engine']
    workdir=jobs.root()/'execution'/job['id']
    workdir.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chdir(workdir)  # existing detector-relative caches stay in this owned job
    # Only private worker configuration controls the provider environment.
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    for key in list(os.environ):
        if key.startswith(('PALIMPSEST_', 'GEMINI_')) and key != 'GEMINI_API_KEY':
            del os.environ[key]
    os.environ.pop('EXA_API_KEY',None)
    os.environ.update(PALIMPSEST_USE_GEMINI='1', GEMINI_JUDGE_MODEL=engine['model'],
                      GEMINI_REVIEWER_MODEL=engine['reviewer_model'], GEMINI_TRIAGE_MODEL=engine['triage_model'],
                      PALIMPSEST_PROMPT=engine['prompt_version'], GEMINI_CONCURRENCY='1')
    if not os.environ.get('GEMINI_API_KEY'):
        raise ValueError('Gemini credential is not configured in the private worker.')
    from google.genai import Client, types
    from google.genai.models import AsyncModels
    import palimpsest.backends.gemini as backend
    adapter_errors=[]
    original_generate=backend._GeminiCaller.generate
    async def validated_generate(self,*args,**kwargs):
        result=await original_generate(self,*args,**kwargs)
        if isinstance(result[0],str):adapter_errors.append('Unvalidated or unavailable detector answer')
        return result
    backend._GeminiCaller.generate=validated_generate
    # SDK retries are disabled. The outer detector may attempt a retry, but the
    # durable exact-request reservation rejects it before any network activity.
    backend.Client = lambda **kw: Client(**kw, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    original = AsyncModels.generate_content

    async def recorded(self, *args, **kwargs):
        disk()
        if kwargs.get('model') not in (engine['model'], engine['reviewer_model'], engine['triage_model']):
            raise ValueError('Unapproved detector model.')
        options = kwargs.get('config')
        if options is not None:
            options.max_output_tokens = engine['max_output_tokens']
        request = serial(dict(args=args, kwargs=kwargs))
        aid, old = jobs.reserve_attempt(job, request)
        if old is not None:
            return types.GenerateContentResponse.model_validate(old)
        progress(job, 'detector', provider_calls=attempts(job)['calls'])
        try:
            value = await original(self, *args, **kwargs)
            jobs.finish_attempt(aid, serial(value))
            return value
        except BaseException as error:
            jobs.finish_attempt(aid, error=type(error).__name__)
            raise

    AsyncModels.generate_content = recorded
    from palimpsest import api
    if api.PROMPT_VERSION != engine['prompt_version']:
        raise ValueError('Configured detector prompt version differs from the deployed code.')
    source = job['sources'][0]
    if job['kind'] == 'page':
        request = api.AuditPageRequest(lang_code=source['lang'], page_title=source['title'],
                                      revision_id=source['revision_id'], wikitext=source['wikitext'])
        response = await api.audit_page(request, api.get_page_consistency_judge())
    else:
        request = api.AuditDiffRequest(lang_code=source['lang'], page_title=source['title'],
            old_revision_id=source['parent_id'], new_revision_id=source['revision_id'],
            editor_username='Authenticated NeoWiki on-demand request',
            old_text=source['parent_wikitext'], new_text=source['wikitext'],
            old_wikitext=source['parent_wikitext'], new_wikitext=source['wikitext'], ref_urls=[])
        response = await api.audit_diff(request, api.get_fetcher(), api.get_judge_backend(), api.get_reviewer_backend(), api.get_auditor_provider())
    value = serial(response)
    if value.get('status', 'ok') != 'ok':
        raise RuntimeError('Detector did not return a successful assessment.')
    value.update(status='ok', _issue_assessment=job['id'], _issue_assessed_at=jobs.now(),
                 on_demand_configuration=config, source_sha256=source['sha256'],
                 parent_sha256=source.get('parent_sha256'), provider_usage=attempts(job))
    unavailable=any(value.get(stage,{}).get('status')=='unavailable' or value.get(stage,{}).get('error')
                    for stage in ('citation_dates','citation_lifecycle','cherry_pick','reviewer'))
    value['adapter_errors']=adapter_errors
    value['partial'] = bool(value.get('partial') or value.get('error') or value['provider_usage']['failed_or_unknown'] or adapter_errors or unavailable)
    if job['kind'] == 'page':
        from palimpsest.page_consistency import candidate_groups, MAX_GROUPS
        value['partial'] = value['partial'] or len(candidate_groups(source['wikitext'])) >= MAX_GROUPS
        value['wikitext'] = source['wikitext']
    else:
        value.update(old_wikitext=source['parent_wikitext'], new_wikitext=source['wikitext'])
    return value


def language(job):
    import live_api
    import article_pipeline as pipeline
    import paired_history
    engine = job['config']['engine']
    if engine['model'] != live_api.MODEL:
        raise ValueError('The configured language model differs from the deployed pipeline.')
    if engine['prompt_version'] != paired_history.VERSION:
        raise ValueError('The configured language prompt version differs from the deployed pipeline.')
    namespace = jobs.digest([job['config'], job.get('previous')])
    os.environ['NEOWIKI_ON_DEMAND_NAMESPACE'] = namespace
    # Group identities and matching/classification policies retain the exact
    # execution namespace. Only this child process sees these module settings.
    pipeline.GROUP_POLICY = 'on-demand-v1:' + namespace[:40]
    original = live_api.requests.post

    def recorded(url, **kwargs):
        if url not in ('https://api.openai.com/v1/decisions', 'https://api.openai.com/v1/responses'):
            raise ValueError('The language worker cannot submit to an unapproved provider endpoint.')
        disk()
        body = json.loads(kwargs['data'])
        if body.get('model') != engine['model']:
            raise ValueError('Unapproved language model.')
        aid, old = jobs.reserve_attempt(job, dict(url=url,body=body))
        if old is not None:
            # live_api's successful cache normally handles this earlier.
            raise RuntimeError('A successful raw provider result requires storage reconciliation; it was not resent.')
        progress(job, 'language_classification', provider_calls=attempts(job)['calls'])
        try:
            response = original(url, **kwargs)
            if not response.ok:
                jobs.finish_attempt(aid, error='HTTP_' + str(response.status_code))
            else:
                jobs.finish_attempt(aid, response.json())
            return response
        except BaseException as error:
            jobs.finish_attempt(aid, error=type(error).__name__)
            raise

    live_api.requests.post = recorded
    sources = job['sources']
    anchors = tuple(pipeline.EditionAnchor(s['lang'],s['page_id'],s['revision_id'],s['title'],s['timestamp']) for s in sources)
    context = pipeline.ArticleContext(job['topic'],sources[0]['title'],anchors,'snapshot',min(s['timestamp'][:10] for s in sources),1)
    result = pipeline.prepare_article(context, lambda r: progress(job, r.get('progress', {}).get('stage','language_comparison'), **{k:v for k,v in r.get('progress', {}).items() if k!='stage'}),
                                      locked_sources=sources, execution=namespace)
    result['provider_usage'] = attempts(job)
    return result


def index_result(job, value):
    import issues
    if job['kind'] == 'language':
        issues.backfill(job['topic'],run_id=value['run'])
        partial = value['progress']['stage'] != 'ready' or value['provider_usage']['failed_or_unknown'] > 0
        return dict(run=value['run'], findings=len(value['rows']), partial=partial, provider_usage=value['provider_usage'])
    from flags_tab import RevisionRef
    source = job['sources'][0]
    ref = RevisionRef(source['lang'],source['revision_id'],source['title'],source['timestamp'],
                      f"https://{source['lang']}.wikipedia.org/w/index.php?oldid={source['revision_id']}",source.get('parent_id'))
    issues.store_scan(job['topic'], ref, value, job['kind'])
    return dict(assessment=value.get('_issue_assessment',job['id']),findings=len(value['flags']),partial=bool(value.get('partial')),
                provider_usage=value.get('provider_usage', {}))


def run_one(identity):
    with jobs.database() as db:
        row = db.execute("SELECT * FROM job WHERE id=? AND status='running'", (identity,)).fetchone()
    if row is None:
        return
    job = dict(row)
    job['config'] = json.loads(job['config'])
    job['sources'] = json.loads(job['sources'])
    try:
        disk()
        jobs.validate_sources(job['sources'])
        if raw_path(identity).exists():
            value = load_result(job)
        else:
            from on_demand_bridge import implementation_identity
            if implementation_identity() != job['config']['implementation']:
                jobs.update(identity, 'blocked_policy', error='Worker code changed. Prepare a new request; this job was not run.')
                return
            allowed, message = jobs.permit(job['config'])
            if not allowed:
                jobs.update(identity, 'blocked_policy', error=message)
                return
            progress(job, 'validating')
            value = compatible_scan(job)
            if value is None:value = language(job) if job['kind'] == 'language' else asyncio.run(detector(job))
            archive(job, value)
        jobs.update(identity, 'awaiting_index', result=dict(raw_saved=True))
        summary = index_result(job, value)
        jobs.update(identity, 'partial' if summary['partial'] else 'completed', result=summary)
    except BaseException as error:
        # Raw successful work is recoverable without another paid call. A failed
        # attempt remains terminal even when the upstream detector swallowed it.
        saved = raw_path(identity).exists()
        status = 'awaiting_index' if saved else 'paused_disk' if isinstance(error, DiskPause) and not attempts(job)['calls'] else 'failed'
        jobs.update(identity, status, error=type(error).__name__ + ': inspect this job before any further request.')


@contextmanager
def worker_lock():
    stream = (jobs.root() / 'worker.lock').open('a+b')
    if os.name == 'nt':
        import msvcrt
        stream.write(b'0');stream.flush();stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'work', 'run-one'))
    parser.add_argument('identity', nargs='?')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.command == 'init':
        jobs.init()
        return
    if args.command == 'run-one':
        run_one(args.identity)
        return
    with worker_lock():
        jobs.recover_interrupted()
        while True:
            try:
                disk()
            except DiskPause:
                if args.once:return
                time.sleep(15)
                continue
            job = jobs.claim()
            if job:
                subprocess.run([sys.executable, __file__, 'run-one', job['id']], check=False)
                # A killed child cannot silently become another paid request.
                jobs.recover_interrupted()
                time.sleep(2)  # storage recovery must not busy-loop on a DB outage
            elif args.once:
                return
            else:
                time.sleep(3)
            if args.once:
                return


if __name__ == '__main__':
    main()
