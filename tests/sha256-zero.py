#!/usr/bin/env python3
"""Zero SHA-256 contexts match hashlib, with reset and sticky-length failure."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
source = ['use "std/crypto/sha2" sha\nuse "std/bytes" bytes']
for length in (0, 1, 3, 55, 56, 63, 64, 65, 1000):
    data = bytes((i * 37 + 11) % 256 for i in range(length))
    text = ''.join('\\x%02x' % byte for byte in data)
    golden = ','.join(map(str, hashlib.sha256(data).digest()))
    source.append(f'''fn case_{length}() {{
  input := "{text}"
  expected:[32]u8=[{golden}]
  zero:sha.Sha256
  explicit:sha.Sha256
  sha.init(&explicit)
  middle:=#len(input)/2
  if !sha.update(&zero,input[..middle]) || !sha.update(&zero,input[middle..]) || !sha.update(&explicit,input) {{ #panic("update") }}
  a:[32]u8=[] b:[32]u8=[]
  if !bytes.equal(sha.finish(&zero,a[..]),expected[..]) || !bytes.equal(sha.finish(&explicit,b[..]),expected[..]) {{ #panic("digest") }}
  sha.init(&zero)
  if !sha.update(&zero,input) || !bytes.equal(sha.finish(&zero,a[..]),expected[..]) {{ #panic("reset") }}
}}''')
source.append('''fn main() {
  empty:sha.Sha256
  digest:[32]u8=[]
  expected:[32]u8=[''' + ','.join(map(str, hashlib.sha256(b'').digest())) + ''']
  if !bytes.equal(sha.finish(&empty,digest[..]),expected[..]) { #panic("zero finish") }
  context:sha.Sha256
  sha.init(&context)
  context.length=2305843009213693951
  if sha.update(&context,"x") || !context.failed { #panic("length overflow") }
  saved:=context.length
  if sha.update(&context,"") || context.length!=saved { #panic("sticky failure") }
  for i in 0..32 { digest[i]=165 }
  if #len(sha.finish(&context,digest[..]))!=0 { #panic("failed finish") }
  for byte in digest { if byte!=165 { #panic("failed output write") } }
  sha.init(&context)
  if !sha.update(&context,"") || context.failed { #panic("reset failure") }
''' + '\n'.join(f'case_{n}()' for n in (0,1,3,55,56,63,64,65,1000)) + '\n}')
with tempfile.TemporaryDirectory(prefix='dyn-sha-zero-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text('\n'.join(source))
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        subprocess.run([str(work/'test')],check=True,timeout=15)
        print('PASS SHA-256 zero/reset/sticky failure '+mode,flush=True)
