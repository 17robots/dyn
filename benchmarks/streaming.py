#!/usr/bin/env python3
"""Compare SDK snapshots with one-byte reads; no timing gate on shared hosts.
Usage: python3 benchmarks/streaming.py [OLD_SDK_DIRECTORY]
"""
import gzip
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
raw=random.Random(61).randbytes(2048);encoded=gzip.compress(raw,mtime=0)
source='''use "std/io" io
use "std/compress/gzip" gzip
use "std/encoding/xml" xml
struct Input { bytes: []const u8, offset: usize }
fn read_one(data: rawptr, output: []u8) io.Result {
  state := #cast(*Input) data
  if state.offset == #len(state.bytes) { return io.Result{ status: io.Status.End } }
  if #len(output) == 0 { return io.Result{} }
  output[0] = state.bytes[state.offset] state.offset += 1
  return io.Result{ transferred: 1 }
}
fn main() {
'''
source+=f'compressed: [{len(encoded)}]u8 = [{",".join(map(str,encoded))}]\n'
source+='''  repeat: usize = 0
  for repeat < 5 {
    input := Input{ bytes: compressed[..] }
    packed: [4096]u8 = [] unpacked: [4096]u8 = [] output: [2048]u8 = []
    decoder := gzip.decoder(io.Reader{ data: #cast(rawptr) &input, read: &read_one }, packed[..], unpacked[..])
    result := io.read_exact(gzip.decoder_reader(&decoder), output[..])
    if result.status == io.Status.Error || result.transferred != 2048 { #panic("gzip workload") }
    repeat += 1
  }
  document: [4096]u8 = []
  document[0] = '<' document[1] = 'r' document[2] = ' ' document[3] = 'a' document[4] = '=' document[5] = 39
  i: usize = 6 for i < 4093 { document[i] = 'x' i += 1 }
  document[4093] = 39 document[4094] = '/' document[4095] = '>'
  xml_input := Input{ bytes: document[..] }
  storage: [4096]u8 = []
  scanner := xml.stream_scanner(io.Reader{ data: #cast(rawptr) &xml_input, read: &read_one }, storage[..])
  if !xml.next_stream(&scanner).ok { #panic("XML workload") }
}
'''
results={}
with tempfile.TemporaryDirectory(prefix='dyn-stream-bench-') as directory:
    path=Path(directory);(path/'main.dyn').write_text(source)
    sdks=[('current',ROOT/'compiler')]
    if len(sys.argv)>1: sdks.insert(0,('before',Path(sys.argv[1]).resolve()))
    for label,sdk in sdks:
        env=dict(os.environ,DYN_SDK=str(sdk))
        subprocess.run([str(ROOT/'build/dyn'),'build',str(path),'--release','--no-cache','--quiet','--output',str(path/'run')],cwd=ROOT,env=env,check=True)
        samples=[]
        for _ in range(5):
            start=time.perf_counter();subprocess.run([str(path/'run')],check=True,timeout=30);samples.append(time.perf_counter()-start)
        results[label]={'seconds':samples,'median_seconds':statistics.median(samples)}
print(json.dumps(results,indent=2))
