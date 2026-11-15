"""Private native Issues service. Run with the existing research environment.

No Flask server, schema creation, backfill, preparation or scan on startup/GET.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from native_issues import authenticated, dispatch
from on_demand_jobs import RequestError


class Handler(BaseHTTPRequestHandler):
    server_version = 'PalimpsestIssues/1'

    def log_message(self, *_args):
        pass  # Do not log identities, evidence, credentials or internal errors.

    def respond(self, status, value):
        body=json.dumps(value,ensure_ascii=False,default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond(405,dict(error='Use the authenticated wiki bridge.'))

    def do_POST(self):
        if self.path != '/v1/issues':
            return self.respond(404,dict(error='Unknown operation.'))
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=65536:
                return self.respond(413,dict(error='Invalid request size.'))
            body=self.rfile.read(size)
            if not authenticated(body,self.headers.get('X-Issues-Time'),self.headers.get('X-Issues-Signature'),self.server.secret):
                return self.respond(403,dict(error='Wiki authentication failed.'))
            payload=json.loads(body)
            if not isinstance(payload,dict):raise ValueError('Invalid request.')
            return self.respond(200,dict(status='ok',data=dispatch(payload)))
        except RequestError as error:
            return self.respond(409,dict(error=str(error)))
        except (ValueError,TypeError):
            return self.respond(400,dict(error='Invalid Issues selection.'))
        except LookupError as error:
            return self.respond(404,dict(error=str(error)))
        except Exception:
            return self.respond(503,dict(error='Stored evidence is unavailable. No inference or automatic retry was started.'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--secret-file',type=Path,required=True)
    args=parser.parse_args()
    secret=args.secret_file.read_text().strip()
    if len(secret)<32:parser.error('Use a private random secret of at least 32 characters.')
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    server.secret=secret
    server.serve_forever()


if __name__=='__main__':main()
