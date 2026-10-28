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
use "std/errors"
use "std/encoding"
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
 arena:=mem.arena_create_bounded(160,8*mem.MiB)
 prefix:=mem.push_bytes_uninit(arena,16)
 mem.fill(prefix,91)
 second:=mem.push_bytes_uninit(arena,256)
 mem.fill(second,77)
 _=mem.arena_push(arena,1,1)
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
 rejected:=b64.decode(f.arena,tail[..4])
 check(!rejected.ok && rejected.detail==encoding.ErrorKind.Overlap && mem.arena_mark(f.arena)==mark)
 check(bytes.equal(tail[..4],"YQ=="))
 check(bytes.equal(b64.decode(f.arena,"aGVsbG8=").value,"hello"))
 check(bytes.equal(b32.decode(f.arena,"NBSWY3DP").value,"hello"))
 check(bytes.equal(hex.decode(f.arena,"68656c6c6f").value,"hello"))
 parsed:=json.parse(f.arena,"{\"answer\":42,\"text\":\"hello\"}")
 check(parsed.ok && json.get(i64,parsed.root,"answer")==42)
 chunked:=http.decode_chunked(f.arena,"5\r\nhello\r\n0\r\n\r\n")
 check(chunked.ok && bytes.equal(chunked.value,"hello"))
 packet:[46]u8=[18,52,129,128,0,1,0,1,0,0,0,0,7,101,120,97,109,112,108,101,4,116,101,115,116,0,0,1,0,1,192,12,0,1,0,1,0,0,0,1,0,4,1,2,3,4]
 answers:=dns.parse_ipv4(f.arena,packet[..],0x1234,"example.test")
 check(answers.ok && #len(answers.value)==1 && answers.value[0].a==1 && answers.value[0].d==4)
 key:[32]u8=[]
 nonce:[12]u8=[]
 sealed:=aead.seal(f.arena,aead.Cipher.Aes256Gcm,"hello","",key[..],nonce[..])
 check(sealed.ok)
 opened:=aead.open(f.arena,aead.Cipher.Aes256Gcm,sealed.value.ciphertext,sealed.value.tag,"",key[..],nonce[..])
 check(opened.ok && bytes.equal(opened.value,"hello"))
 PROCESS_CASE
 intact(f)
}
'''
def main():
    source=SOURCE.replace('PROCESS_CASE', 'arguments:[3][]const u8=["/bin/sh","-c","printf chain"]\n captured:=process.capture(f.arena,"/bin/sh",arguments[..],process.Options{},process.CaptureOptions{timeout_milliseconds:2000})\n check(captured.ok && captured.exit.code==0 && bytes.equal(captured.output,"chain"))' if sys.platform=='linux' else '_=process.Options{}')
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
