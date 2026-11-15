"""Launch only the private native Issues bridge, independently of previews.

Use the installed research interpreter. Does not start Docker, alter schemas,
import articles, load a model, or start inference.
"""
from pathlib import Path
import argparse
import os
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-python',type=Path,required=True)
    parser.add_argument('--research-root',type=Path,required=True)
    parser.add_argument('--secret-file',type=Path,default=ROOT/'.local/native-issues/bridge-secret')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--native-wikis',help='JSON mapping of edition to native index.php URL')
    args=parser.parse_args()
    secret=args.secret_file.resolve()
    # The bridge secret is deliberately unrelated to provider credentials.
    if not secret.exists():
        secret.parent.mkdir(parents=True,exist_ok=True)
        with secret.open('x',encoding='utf-8') as stream:stream.write(secrets.token_hex(32))
        secret.chmod(0o600)
    env=os.environ.copy();env['NEOWIKI_RESEARCH_ROOT']=str(args.research_root.resolve());env['PYTHONDONTWRITEBYTECODE']='1'
    if args.native_wikis:
        import json
        json.loads(args.native_wikis)
        env['PALIMPSEST_NATIVE_WIKIS']=args.native_wikis
    raise SystemExit(subprocess.run([str(args.app_python.resolve()),'-B','native_issues_server.py',
        '--host',args.host,'--port',str(args.port),'--secret-file',str(secret)],
        cwd=ROOT/'tools/language-gap-explorer',env=env).returncode)

if __name__=='__main__':main()
