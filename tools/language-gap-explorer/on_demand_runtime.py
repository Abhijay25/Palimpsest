"""Private container entry point. Credentials are loaded only for the worker."""
import os
from pathlib import Path
import sys


def secret(name):
    filename=os.environ.get(name+'_FILE')
    if filename:
        value=Path(filename).read_text(encoding='utf-8').strip()
        if not value:raise RuntimeError('Required private secret file is empty.')
        os.environ[name]=value


def main():
    role=sys.argv[1] if len(sys.argv)>1 else ''
    if role not in ('init','worker','bridge','batch'):raise SystemExit('Choose init, worker, bridge or batch.')
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    secret('DB_PASSWORD')
    if role=='worker':
        secret('GEMINI_API_KEY');secret('OPENAI_API_KEY')
    else:
        for name in ('GEMINI_API_KEY','OPENAI_API_KEY','OPEN_API_KEY'):
            os.environ.pop(name,None)
    base=Path(__file__).resolve().parent
    if role=='init':
        from on_demand_jobs import init
        init()
        return
    command=[sys.executable,str(base/('on_demand_worker.py' if role=='worker' else 'on_demand_batch.py' if role=='batch' else 'native_issues_server.py'))]
    command+=['work'] if role=='worker' else sys.argv[2:]
    os.execv(sys.executable,command)


if __name__=='__main__':main()
