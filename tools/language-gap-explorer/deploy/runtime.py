"""Load mounted secret files, then exec one explicit container command."""
import os
from pathlib import Path
import sys


def load_secret(name, required=False):
    filename = os.environ.get(name + '_FILE')
    if filename:
        value = Path(filename).read_text(encoding='utf-8').strip()
        if not value:
            raise RuntimeError('A required runtime secret file is empty: ' + name)
        os.environ[name] = value
    if required and not os.environ.get(name):
        raise RuntimeError('A required runtime secret is missing: ' + name)


def configure():
    role = os.environ.get('NEOWIKI_ROLE', 'reader')
    if role not in {'reader', 'init', 'worker'}:
        raise RuntimeError('Invalid container role.')
    load_secret('DB_PASSWORD', required=True)
    if role == 'reader':
        # Workers have a different secret mount; the reader never receives it.
        for name in ('OPENAI_API_KEY', 'OPEN_API_KEY', 'OPENAI_API_KEY_FILE', 'OPEN_API_KEY_FILE'):
            os.environ.pop(name, None)
        load_secret('NEOWIKI_SESSION_SECRET', required=True)
    elif role == 'worker':
        load_secret('OPENAI_API_KEY', required=True)
    root = Path(os.environ.get('NEOWIKI_RESEARCH_ROOT', '/var/lib/neowiki')).resolve()
    if role == 'reader' and any((root / name).exists() for name in ('.env', '.env.local')):
        raise RuntimeError('Reader runtime root must not contain provider environment files.')


if __name__ == '__main__':
    configure()
    if len(sys.argv) < 2:
        raise SystemExit('Pass an explicit container command.')
    os.execvp(sys.argv[1], sys.argv[1:])
