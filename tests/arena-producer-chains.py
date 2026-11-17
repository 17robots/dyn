#!/usr/bin/env python3
"""Small owned blocks exercise std producers after prior chained growth."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/mem"
use "std/bytes"
use "std/io" errors
use "std/fail"
use "std/encoding/base32" b32
use "std/encoding/base64" b64
use "std/encoding/hex"
use "std/encoding/json"
use "std/net/dns"
use "std/net/http"
use "std/crypto/aead"
use "std/process"
fn check(ok:bool) { if !ok { #panic("chained producer contract") } }
struct Fixture { arena:*mem.Arena, prefix:[]u8, second:[]u8 }
fn fresh() Fixture {
 source:=mem.pages(8*mem.MiB)
 source.block_size=160
 arena:=mem.arena_from_source(source)
 prefix:=mem.push_bytes(arena,16)
 mem.fill(prefix,91)
 second:=mem.push_bytes(arena,256)
 mem.fill(second,77)
 _=mem.push(u8,arena)
 check(mem.arena_mark(arena)>#len(arena.data))
 return Fixture{arena:arena,prefix:prefix,second:second}
}
fn intact(f:Fixture) {
 for b in f.prefix { check(b==91) }
 for b in f.second { check(b==77) }
}
fn main() {
 f:=fresh()
 defer mem.arena_release(f.arena)
 check(!mem.arena_overlaps_unallocated(f.arena,f.prefix))
 check(!mem.arena_overlaps_unallocated(f.arena,f.second))
 tail:=f.arena.current.data[f.arena.current.offset..]
 check(mem.arena_overlaps_unallocated(f.arena,tail))
 _=mem.copy(tail,"YQ==")
 mark:=mem.arena_mark(f.arena)
 rejected:fail.Status
 _=b64.decode(f.arena,&rejected,tail[..4])
 check(rejected.failure.kind==fail.Kind.InvalidInput && mem.arena_mark(f.arena)==mark)
 check(bytes.equal(tail[..4],"YQ=="))
 status:fail.Status
 check(bytes.equal(b64.decode(f.arena,&status,"aGVsbG8="),"hello"))
 check(bytes.equal(b32.decode(f.arena,&status,"NBSWY3DP"),"hello"))
 check(bytes.equal(hex.decode(f.arena,&status,"68656c6c6f"),"hello"))
 root:=json.parse(f.arena,&status,"{\"answer\":42,\"text\":\"hello\"}")
 check(!status.failed && json.get(i64,root,"answer")==42)
 chunked:=http.decode_chunked(f.arena,&status,"5\r\nhello\r\n0\r\n\r\n")
 check(!status.failed && bytes.equal(chunked.value,"hello"))
 packet:[46]u8=[18,52,129,128,0,1,0,1,0,0,0,0,7,101,120,97,109,112,108,101,4,116,101,115,116,0,0,1,0,1,192,12,0,1,0,1,0,0,0,1,0,4,1,2,3,4]
 answers:=dns.parse_ipv4(f.arena,&status,packet[..],0x1234,"example.test")
 check(!status.failed && #len(answers)==1 && answers[0].a==1 && answers[0].d==4)
 key:[32]u8
 nonce:[12]u8
 sealed:=aead.seal(f.arena,&status,aead.Cipher.Aes256Gcm,"hello","",key[..],nonce[..])
 opened:=aead.open(f.arena,&status,aead.Cipher.Aes256Gcm,sealed.ciphertext,sealed.tag,"",key[..],nonce[..])
 check(!status.failed && bytes.equal(opened,"hello"))
 PROCESS_CASE
 intact(f)
}
'''
def main():
    source=SOURCE.replace('PROCESS_CASE', 'arguments:[3][]const u8=["/bin/sh","-c","printf chain"]\n captured:=process.capture(f.arena,&status,"/bin/sh",arguments[..],process.Options{},process.CaptureOptions{timeout_milliseconds:2000})\n check(!status.failed && captured.exit.code==0 && bytes.equal(captured.output,"chain"))' if sys.platform=='linux' else '_=process.Options{}')
    with tempfile.TemporaryDirectory(prefix='dyn-chain-producers-') as temporary:
        project=Path(temporary)
        (project/'main.dyn').write_text(source)
        for mode,tree in [('debug',False),('release',False),('release',True)]:
            env=dict(os.environ,DYN_SDK=str(ROOT))
            if tree:env['DYN_NO_SSA']='1'
            else:env.pop('DYN_NO_SSA',None)
            output=project/('run.exe' if os.name=='nt' else 'run')
            subprocess.run([DYN,'build',str(project),'--'+mode,'--quiet','--no-cache','--output',str(output)],env=env,check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=15)
            print('PASS chained producers',mode,'tree' if tree else 'default',flush=True)
    if sys.platform!='linux':print('SKIP Linux process-capture chain subcase')
if __name__=='__main__':main()
