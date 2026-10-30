#!/usr/bin/env python3
"""Small default arenas stay small resident under transparent huge pages."""
import os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];DYN=str(Path(os.environ.get('DYN',R/'build/dyn-release')).resolve())
if not sys.platform.startswith('linux'):
 print('SKIP arena resident: Linux /proc only');sys.exit(0)
COUNT=32
SOURCE=r'''use "std/mem"
fn wait() {
 ready:="ready\n"
 _=#syscall(1,1,&ready[0],#len(ready))
 input:[1]u8=[]
 _=#syscall(0,0,&input[0],1)
}
fn main() {
 wait()
 arenas:[COUNT]*mem.Arena=[]
 for i in 0..COUNT {
  arenas[i]=mem.arena_create(0)
  bytes:=mem.push_bytes_uninit(arenas[i],64)
  for *byte in bytes { byte.*=1 }
 }
 wait()
 for i in 0..COUNT { mem.arena_release(arenas[i]) }
}
'''.replace('COUNT',str(COUNT))
def anonymous(pid):
 for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
  if line.startswith('Anonymous:'):return int(line.split()[1])
with tempfile.TemporaryDirectory(prefix='dyn-arena-resident-') as tmp:
 p=Path(tmp);(p/'main.dyn').write_text(SOURCE)
 for mode in ('debug','release'):
  binary=p/mode;subprocess.run([DYN,'build',str(p),'--'+mode,'--no-cache','--quiet','--output',str(binary)],env=dict(os.environ,DYN_SDK=str(R)),check=True,timeout=120)
  child=subprocess.Popen([str(binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
  try:
   assert child.stdout.readline()==b'ready\n'
   before=anonymous(child.pid)
   child.stdin.write(b'x');child.stdin.flush()
   assert child.stdout.readline()==b'ready\n'
   grown=anonymous(child.pid)-before
   child.stdin.write(b'x');child.stdin.flush()
   assert child.wait(timeout=10)==0
  finally:
   if child.poll() is None:child.kill()
  # One 4 KiB header page per arena; a huge-page fault would cost 2048 KiB each.
  assert grown<=COUNT*64,(mode,'anonymous growth KiB',grown)
  print(f'PASS arena resident {mode}: {COUNT} arenas grew {grown} KiB anonymous')
