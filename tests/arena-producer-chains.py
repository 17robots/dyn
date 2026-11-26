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
use errors "std/io"
use "std/fail"
use b32 "std/encoding/base32"
use b64 "std/encoding/base64"
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
 _=mem.push<u8>(arena)
 check(mem.arena_mark(arena)>arena.data.len)
 return Fixture{arena:arena,prefix:prefix,second:second}
}
fn intact(f:Fixture) {
 for b in f.prefix { check(b==91) }
 for b in f.second { check(b==77) }
}
fn b64_fails(arena:*mem.Arena,text:[]const u8) bool {
 _=b64.decode(arena,text) catch { return true }
 return false
}
fn main() {
 f:=fresh()
 defer mem.arena_release(f.arena)
 check(!mem.arena_overlaps_unallocated(f.arena,f.prefix))
 check(!mem.arena_overlaps_unallocated(f.arena,f.second))
 tail:=f.arena.current.data[f.arena.current.offset..]
 check(mem.arena_overlaps_unallocated(f.arena,tail))
 // Malformed input in the free space fails before the overlap check (valid
 // input there panics) and leaves the arena and the input alone.
 _=mem.copy(tail,"Y!==")
 mark:=mem.arena_mark(f.arena)
 check(b64_fails(f.arena,tail[..4]) && mem.arena_mark(f.arena)==mark)
 check(bytes.equal(tail[..4],"Y!=="))
 status:fail.Status
 decoded:=b64.decode(f.arena,"aGVsbG8=") catch { #panic("base64") }
 check(bytes.equal(decoded,"hello"))
 decoded=b32.decode(f.arena,"NBSWY3DP") catch { #panic("base32") }
 check(bytes.equal(decoded,"hello"))
 decoded=hex.decode(f.arena,"68656c6c6f") catch { #panic("hex") }
 check(bytes.equal(decoded,"hello"))
 root:=json.parse(f.arena,"{\"answer\":42,\"text\":\"hello\"}") catch { #panic("json") }
 check((json.get<i64>(root, "answer") catch 0)==42)
 chunked:=http.decode_chunked(f.arena,"5\r\nhello\r\n0\r\n\r\n") catch { #panic("chunked") }
 check(!status.failed && bytes.equal(chunked.value,"hello"))
 packet:[46]u8=[18,52,129,128,0,1,0,1,0,0,0,0,7,101,120,97,109,112,108,101,4,116,101,115,116,0,0,1,0,1,192,12,0,1,0,1,0,0,0,1,0,4,1,2,3,4]
 answers:=dns.parse_ipv4(f.arena,packet[..],0x1234,"example.test") catch { #panic("dns") }
 check(!status.failed && answers.len==1 && answers[0].a==1 && answers[0].d==4)
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
    source=SOURCE.replace('PROCESS_CASE', 'arguments:[3][]const u8=["/bin/sh","-c","printf chain"]\n captured:=process.capture(f.arena,"/bin/sh",arguments[..],process.Options{},process.CaptureOptions{timeout_milliseconds:2000}) catch { #panic("capture") }\n check(captured.exit.code==0 && bytes.equal(captured.output,"chain"))' if sys.platform=='linux' else '_=process.Options{}')
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
