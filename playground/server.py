#!/usr/bin/env python3
"""Local Dyn playground backed by the fail-closed Linux sandbox runner."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dyn_sandbox',ROOT/'compiler/tools/dyn-sandbox.py')
sandbox=importlib.util.module_from_spec(spec);spec.loader.exec_module(sandbox)


def serve(host,port,dyn,sdk,runtimes,token,external_origin=None):
    slots=threading.BoundedSemaphore(2)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup();self.connection.settimeout(30)
        def respond(self,status,body,kind='application/json'):
            payload=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(payload)
        def allowed_host(self):
            hosts = {f'{host}:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if external_origin: hosts.add(urlsplit(external_origin).netloc)
            return self.headers.get('Host') in hosts
        def do_GET(self):
            if not self.allowed_host(): self.respond(403,{'error':'invalid host'});return
            files={'/':'index.html','/main.js':'main.js','/style.css':'style.css'}
            name=files.get(urlsplit(self.path).path)
            if not name: self.respond(404,{'error':'not found'});return
            types={'index.html':'text/html; charset=utf-8','main.js':'text/javascript','style.css':'text/css'}
            self.respond(200,(Path(__file__).parent/name).read_bytes(),types[name])
        def do_POST(self):
            if not self.allowed_host() or not hmac.compare_digest(self.headers.get('X-Dyn-Token',''),token):
                self.respond(403,{'error':'invalid access token or host'});return
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{host}:{self.server.server_port}',f'http://localhost:{self.server.server_port}',external_origin}:
                self.respond(403,{'error':'cross-origin request denied'});return
            if self.path!='/run' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.respond(400,{'error':'POST /run with application/json required'});return
            try: length=int(self.headers.get('Content-Length','0'))
            except ValueError: length=0
            if not 0<length<=65536: self.respond(413,{'error':'source request limit is 64 KiB'});return
            if not slots.acquire(blocking=False): self.respond(429,{'error':'both workers busy'});return
            try:
                request=json.loads(self.rfile.read(length))
                if not isinstance(request,dict): raise ValueError('request must be an object')
                source=request.get('source')
                if not isinstance(source,str): raise ValueError('source must be text')
                report=sandbox.run_source(source,dyn,sdk,runtimes)
                self.respond(200,report)
            except (ValueError,OSError,RuntimeError) as error:
                self.respond(400,{'error':str(error)})
            finally: slots.release()
        def log_message(self,format,*args):
            # Never log URL fragments/tokens or submitted source.
            pass
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'Dyn playground: http://{host}:{server.server_port}/#token={token}',flush=True)
    server.serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--origin',help='Exact HTTPS origin of an authenticated port-forwarding proxy')
    parser.add_argument('--dyn',default=str(ROOT/'build/dyn'))
    parser.add_argument('--sdk',default=str(ROOT/'compiler'))
    parser.add_argument('--runtimes',default=str(ROOT/'build'))
    args=parser.parse_args()
    if args.origin:
        parsed=urlsplit(args.origin)
        if parsed.scheme!='https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            parser.error('--origin must be an HTTPS origin without path or credentials')
    # Public deployment goes through an authenticated reverse proxy and dedicated host.
    serve('127.0.0.1',args.port,args.dyn,args.sdk,args.runtimes,secrets.token_urlsafe(32),args.origin)
