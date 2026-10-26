#!/usr/bin/env python3
"""Independent failure controls for the benchmark's process lifecycle helpers."""
import ast,os,select,signal,subprocess,sys,tempfile,time
from pathlib import Path
SOURCE=Path(__file__).with_name('run.py')
nodes=ast.parse(SOURCE.read_text()).body
chosen=[n for n in nodes if isinstance(n,ast.FunctionDef) and n.name in ('terminate','run','start_server')]
with tempfile.TemporaryDirectory(prefix='dyn-app-harness-') as directory:
    out=Path(directory)
    ns=dict(os=os,select=select,signal=signal,subprocess=subprocess,time=time,ENV=dict(os.environ),OUT=out,commands={})
    exec(compile(ast.Module(body=chosen,type_ignores=[]),str(SOURCE),'exec'),ns)
    childpid=out/'child.pid'
    code='import subprocess,time;from pathlib import Path;p=subprocess.Popen(["'+sys.executable+'","-c","import time;time.sleep(30)"]);Path('+repr(str(childpid))+').write_text(str(p.pid));time.sleep(30)'
    try:ns['run']([sys.executable,'-c',code],timeout=.3)
    except subprocess.TimeoutExpired:pass
    else:raise AssertionError('timeout did not fire')
    pid=int(childpid.read_text());status=Path(f'/proc/{pid}/stat')
    assert not status.exists() or status.read_text().split()[2]=='Z','descendant survives timeout'
    for name,text in [('partial',"print('port ',end='',flush=True)"),('invalid',"print('port not-a-number',flush=True)"),('range',"print('port 0',flush=True)")]:
        script=out/f'{name}.py';script.write_text('import time,os\nfrom pathlib import Path\nPath('+repr(str(out/(name+'.pid')))+').write_text(str(os.getpid()))\n'+text+'\ntime.sleep(30)\n')
        ns['commands'][name]=[sys.executable,'-u',str(script)]
        try:ns['start_server'](name,timeout=.3)
        except (ValueError,RuntimeError):pass
        else:raise AssertionError('startup failure was accepted')
        pid=int((out/(name+'.pid')).read_text());assert not Path(f'/proc/{pid}').exists(),'server survives invalid startup'
print('PASS harness controls: child timeout, partial readiness, invalid port, port range; no live descendants')
