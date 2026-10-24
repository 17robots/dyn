"""Application ports using only Python's standard library."""
import json,os,sys,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
MAX=2**53-1
SERVICES=[f'svc{i:02}' for i in range(16)]
def reject_constant(value):raise ValueError("invalid JSON constant")
def aggregate(records):
    totals=[0]*4;groups=[[0]*4 for _ in SERVICES]
    for obj in records:
        if not isinstance(obj,dict) or not isinstance(obj.get('service'),str):raise ValueError('object/service')
        try:index=SERVICES.index(obj['service'])
        except ValueError:raise ValueError('service') from None
        values=[]
        for name in ('status','bytes','latency_us'):
            x=obj.get(name)
            if type(x) not in (int,float) or not 0<=x<=MAX or int(x)!=x:raise ValueError('numeric field')
            values.append(int(x))
        status,size,latency=values
        if status>599:raise ValueError('status')
        row=[1,size,latency,int(status>=500)]
        for i,n in enumerate(row):
            totals[i]+=n;groups[index][i]+=n
            if totals[i]>MAX:raise ValueError('total overflow')
    return dict(zip(('records','bytes','latency_us','errors'),totals),services=groups)
def search(directory):
    total=dict(files=0,bytes=0,lines=0,matching_lines=0,matching_files=0)
    def walk(path):
        with os.scandir(path) as entries:
            for e in entries:
                if e.is_dir(follow_symlinks=False):walk(e.path)
                elif e.is_file(follow_symlinks=False) and e.name.endswith('.txt'):
                    with open(e.path,'rb') as f:data=f.read()
                    lines=data.split(b'\n') if data else []
                    if data.endswith(b'\n'):lines.pop()
                    matches=sum(b'ERROR' in line for line in lines)
                    total['files']+=1;total['bytes']+=len(data);total['lines']+=len(lines);total['matching_lines']+=matches;total['matching_files']+=int(matches>0)
    walk(directory);return total
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def reply(self,status,body,kind='application/json'):
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Connection','close');self.end_headers();self.wfile.write(body);self.close_connection=True
    def do_GET(self):
        self.reply(200,b'ok\n','text/plain') if self.path=='/health' else self.reply(404,b'not found\n','text/plain')
    def do_POST(self):
        if self.path=='/quit':
            self.reply(200,b'bye\n','text/plain');threading.Thread(target=self.server.shutdown,daemon=True).start();return
        if self.path!='/summarize':self.reply(404,b'not found\n','text/plain');return
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<=n<=1024*1024:raise ValueError('length')
            data=json.loads(self.rfile.read(n),parse_constant=reject_constant)
            if not isinstance(data,list):raise ValueError('array required')
            result=aggregate(data)
        except (ValueError,TypeError,OverflowError,UnicodeError,RecursionError):self.reply(400,b'invalid\n','text/plain');return
        self.reply(200,json.dumps(result,separators=(',',':')).encode())
def main():
    if len(sys.argv)==2 and sys.argv[1]=='serve':
        with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
            server.daemon_threads=True;print('port',server.server_address[1],flush=True);server.serve_forever(poll_interval=.01)
        return
    if len(sys.argv)!=3:raise ValueError('usage: report FILE | search DIRECTORY | serve')
    mode,path=sys.argv[1:]
    if mode=='report':
        with open(path,'rb') as f:data=f.read()
        result=aggregate(json.loads(line,parse_constant=reject_constant) for line in data.split(b'\n') if line)
    elif mode=='search':result=search(path)
    else:raise ValueError('mode')
    print(json.dumps(result,separators=(',',':')))
if __name__=='__main__':
    try:main()
    except (ValueError,TypeError,OSError,OverflowError,UnicodeError,RecursionError) as e:print(str(e),file=sys.stderr);sys.exit(2)
