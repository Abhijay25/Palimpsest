"""Run the research preview and its detector together; stop both on Ctrl+C."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-python', default=sys.executable)
    parser.add_argument('--detector-python', default=sys.executable)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--research-root', type=Path)
    parser.add_argument('--port', type=int, default=8025)
    parser.add_argument('--detector-port', type=int, default=8765)
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.port, args.detector_port)) or args.port == args.detector_port:
        parser.error('Choose two distinct ports between 1 and 65535.')
    env_file = args.env_file.resolve() if args.env_file else None
    if env_file and not env_file.is_file():
        parser.error('The selected environment file does not exist.')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    if env_file:
        from dotenv import dotenv_values
        # Share one private configuration between both services; never print it.
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                env.setdefault(key, value)
    if args.research_root:
        env['NEOWIKI_RESEARCH_ROOT'] = str(args.research_root.resolve())
    # The detector imports this environment file privately through uvicorn.
    detector = [args.detector_python, '-B', '-m', 'uvicorn', 'palimpsest.api:app',
                '--host', '127.0.0.1', '--port', str(args.detector_port)]
    if env_file:
        detector += ['--env-file', str(env_file)]
    origin = f'http://127.0.0.1:{args.detector_port}'
    # Do not accidentally attach the preview to an unrelated listener.
    import socket
    for port in (args.port, args.detector_port):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                parser.error(f'Port {port} is already in use. Stop that preview or choose another port.')
    children = []
    try:
        api = subprocess.Popen(detector, cwd=root, env=env)
        children.append(api)
        deadline = time.monotonic() + 30
        health = None
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError('Detector exited during startup. Install the root project dependencies first.')
            try:
                with urlopen(origin + '/healthz', timeout=1) as response:
                    health = json.load(response)
                break
            except (OSError, ValueError):
                time.sleep(.25)
        if health is None:
            raise RuntimeError('The detector did not become ready within 30 seconds.')
        if not health.get('judge_configured'):
            print('Detector is running without a configured Gemini judge. Scanning will stay disabled.', flush=True)
        frontend_env = dict(env, PALIMPSEST_API_URL=origin)
        frontend = subprocess.Popen(
            [args.app_python, '-B', '-m', 'flask', '--app', 'app', 'run',
             '--host', '127.0.0.1', '--port', str(args.port)],
            cwd=root / 'tools' / 'language-gap-explorer', env=frontend_env)
        children.append(frontend)
        print(f'Article preview: http://127.0.0.1:{args.port}/explore', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(.5)
        raise RuntimeError('A preview service stopped. Both services have been stopped; check the output above.')
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
