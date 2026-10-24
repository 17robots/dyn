#!/usr/bin/env python3
"""Experimental compact JSON DOM: independent expected trees and ownership edges."""
from pathlib import Path
import json,random,subprocess,os,struct,tempfile,sys
R=Path(__file__).resolve().parents[1];DYN=Path(os.environ.get('DYN',R/'build/dyn-release')).resolve();holder=tempfile.TemporaryDirectory(prefix='dyn-json-read-');W=Path(holder.name);P=W/'proof';P.mkdir();env=dict(os.environ,DYN_SDK=os.environ.get('DYN_SDK',str(R)));rng=random.Random(20261024)
def quote(x):return '"'+''.join('\\x%02x'%b for b in x)+'"'
def check(node,v,label):
 out=[]
 def req(s):out.append('require('+s+','+quote(label.encode())+')')
 if v is None:req('json.kind('+node+')==json.KindNull')
 elif isinstance(v,bool):req('json.kind('+node+')==json.KindBool && json.as_bool('+node+')=='+str(v).lower())
 elif isinstance(v,str):req('json.kind('+node+')==json.KindString && mem.equal(json.as_text('+node+'),'+quote(v.encode())+')')
 elif isinstance(v,(int,float)):
  bits=struct.unpack('<Q',struct.pack('<d',float(v)))[0];req('json.kind('+node+')==json.KindNumber && #bitcast(u64,json.as_f64('+node+'))=='+str(bits))
 elif isinstance(v,list):
  req('json.kind('+node+')==json.KindArray && json.length('+node+')=='+str(len(v)))
  for i,x in enumerate(v):out+=check('json.at('+node+','+str(i)+')',x,label)
  req('json.kind(json.at('+node+','+str(len(v))+'))==json.KindMissing')
 else:
  req('json.kind('+node+')==json.KindObject && json.length('+node+')=='+str(len(v)))
  for k,x in v.items():out+=check('json.get('+node+','+quote(k.encode())+')',x,label)
  req('json.kind(json.get('+node+',"not_present_zzz"))==json.KindMissing')
 return out
values=[None,True,False,0,-0.0,1,-1,2**64-1,-2**63,2**53-1,1.25,1e300,1e-300,'','ascii','é😀','a\0b\n\\"',{'é😀':'café','a\0b':[True,None]},[],{},[1,2,{'x':'y'}]]
values.append({'é😀':'café','a\0b':[True,None]})
for i in range(60):values.append({'id':i,'key'+str(i):['x'*(i%17),'é😀',i%2==0,None,{'nested':i*19}],'escaped':'a\nb\t"\\'})
lines=['use "std/encoding/json/read" json','use "std/encoding/json" mutable','use "std/mem" mem','use "std/io"','fn require(ok:bool,label:[]const u8) { if !ok { #panic(label) } }','fn main() {','require(#sizeof(json.Value)==16,"compact value size")','arena:=mem.arena_create(mem.MiB) defer mem.arena_release(&arena)','_=mem.push_bytes_uninit(&arena,3)']
for i,v in enumerate(values):
 raw=json.dumps(v,ensure_ascii=i%2==0,separators=(',',':')).encode();lines+=['if true {',f'original:={quote(raw)}','input:=mem.push_bytes_uninit(&arena,#len(original)) _=mem.copy(input,original)','mark:=mem.arena_mark(&arena)','result:=json.parse(&arena,input)','require(result.ok && result.kind==json.Kind.None && result.error==0,"valid metadata")','for i in 0..#len(input) { input[i]=255 }']
 # errors is not re-exported as Kind; use zero enum via cast.
 lines[-2]=lines[-2].replace('result.kind==json.Kind.None','#cast(usize,result.kind)==0')
 lines+=check('result.root',v,'value '+str(i));lines+=['mem.arena_rewind(&arena,mark)','mem.arena_rewind(&arena,3)','}']
invalid=[b'',b' ',b'01',b'1.',b'1e',b'-',b'true false',b'"x" trailing',b'{"a":}',b'[1,]',b'{"a" 1}',b'"unterminated',b'"bad\\q"',b'"bad\\"',b'"\\u12"',b'"\\u00xz"',b'"\\ud800"',b'"\\udc00"',b'"\\ud800\\u0041"',b'"\xc0\xaf"',b'"\xed\xa0\x80"',b'"\xf4\x90\x80\x80"',b'"\xe2\x82"',b'"\x80"',b'['*257+b'0'+b']'*257,b'1e9999']+[b'"a'+bytes([x])+b'b"' for x in range(32)]
invalid += [b'['*n for n in range(1,258)] + [b'{\"x\":'*n for n in range(1,65)]
for i,raw in enumerate(invalid):lines+=['if true {',f'result:=json.parse(&arena,{quote(raw)})','require(!result.ok && json.kind(result.root)==json.KindMissing && mem.arena_mark(&arena)==3,"invalid rollback")','}']
large=json.dumps(list(range(1000)),separators=(',',':')).encode();deep=b'['*256+b'0'+b']'*256
lines += ['if true {',f'result:=json.parse(&arena,{quote(large)})','require(result.ok && json.length(result.root)==1000,"growth array")','for i in 0..1000 { require(json.as_f64(json.at(result.root,i))==#cast(f64,i),"contiguous growth") }','require(result.root.bits==1001,"subtree span")','mem.arena_rewind(&arena,3)','}',f'require(json.parse(&arena,{quote(deep)}).ok,"depth 256")','mem.arena_rewind(&arena,3)','if true {','backing:[512]u8=[] fixed:=mem.arena_from_buffer(backing[..])','result:=json.parse(&fixed,"{\\"x\\":1}")','require(result.ok && json.as_f64(json.get(result.root,"x"))==1.0,"fixed buffer")','}', 'if true {','storage:[1024]u8=[] fixed:=mem.arena_from_buffer(storage[..])','input:=storage[10..20] _=mem.copy(input,"[1,2,3,4] ")','result:=json.parse(&fixed,input)','require(!result.ok && fixed.offset==0 && mem.equal(input,"[1,2,3,4] "),"alias rejection")','}', 'require(json.kind(nil)==json.KindMissing && json.kind(json.get(nil,"x"))==json.KindMissing,"nil navigation")','}']
edge_source = r'''
if true {
  value:=json.parse(&arena,"-0")
  require(value.ok && #bitcast(u64,json.as_f64(value.root))==9223372036854775808,"negative integer zero")
  mem.arena_rewind(&arena,3)
}
if true {
  value:=json.parse(&arena,"{\"\":1,\"dup\":2,\"dup\":3}")
  require(value.ok && json.as_u64(json.get(value.root,""))==1 && json.as_u64(json.get(value.root,"dup"))==2,"empty and duplicate keys")
  it:=json.iterator(value.root)
  require(json.next(&it).ok && json.next(&it).ok && json.next(&it).ok && !json.next(&it).ok,"object iterator count")
  mem.arena_rewind(&arena,3)
}
if true {
  value:=json.parse(&arena,"18446744073709551615")
  require(value.ok && json.as_u64(value.root)==18446744073709551615 && json.as_i64(value.root)==0,"unsigned maximum")
  mem.arena_rewind(&arena,3)
  value=json.parse(&arena,"-9223372036854775808")
  require(value.ok && json.as_i64(value.root)==-9223372036854775807-1 && json.as_u64(value.root)==0,"signed minimum")
  mem.arena_rewind(&arena,3)
  value=json.parse(&arena,"-1e9999")
  require(!value.ok && value.detail==json.ErrorKind.NumberOverflow && value.error==0,"real negative overflow")
  require(mem.arena_mark(&arena)==3,"real overflow rollback")
}
for pad in 0..16 {
  backing:[4096]u8=[]
  fixed:=mem.arena_from_buffer(backing[pad..])
  result:=json.parse(&fixed,"{\"x\":[0,true,\"a\\u0000b\"],\"y\":-1.25}")
  require(result.ok && (#cast(usize,result.root)&7)==0,"misaligned backing")
  require(json.length(json.get(result.root,"x"))==3 && json.as_f64(json.get(result.root,"y"))==-1.25,"misaligned values")
  it:=json.iterator(json.get(result.root,"x"))
  require(json.as_u64(json.next(&it).value)==0 && json.as_bool(json.next(&it).value),"array iterator")
  item:=json.next(&it)
  require(item.ok && mem.equal(json.as_text(item.value),"a\x00b") && !json.next(&it).ok,"iterator decoded bytes")
}
if true {
  backing:[80]u8=[] fixed:=mem.arena_from_buffer(backing[..])
  result:=json.parse(&fixed,"\"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\"")
  require(result.ok && fixed.offset==80 && fixed.peak_used==80,"scalar exact capacity")
}
'''
# Keys and scalar values remain permitted at the maximum container depth.
# This specifically protects direct key dispatch from acquiring a container
# depth check, and compares malformed key offsets against the mutable parser.
key_edges=[]
for scalar,kind in [(b'""','String'),(b'"value"','String'),(b'null','Null'),(b'true','Bool'),(b'42','Number')]:
 raw=b'['*255+b'{"\\u006b":'+scalar+b'}'+b']'*255
 key_edges += ['if true {',f'raw:={quote(raw)}','result:=json.parse(&arena,raw)','require(result.ok,"maximum-depth object key and scalar")','node:=result.root','for depth in 0..255 { node=json.at(node,0) }',f'require(json.kind(json.get(node,"k"))==json.Kind{kind},"maximum-depth scalar kind")','mem.arena_rewind(&arena,3)','other:=mutable.parse(&arena,raw)','require(other.ok,"mutable maximum-depth control")','mem.arena_rewind(&arena,3)','}']
for raw in [b'{"\\q":0}',b'{"\\ud800":0}',b'{"\\u006b" 0}',b'['*255+b'{"\\q":0}'+b']'*255,b'['*256+b'{"k":0}'+b']'*256]:
 key_edges += ['if true {',f'raw:={quote(raw)}','result:=json.parse(&arena,raw)','require(!result.ok && json.is_missing(result.root) && mem.arena_mark(&arena)==3,"key failure rollback")','other:=mutable.parse(&arena,raw)','require(!other.ok && result.offset==other.offset && result.kind==other.kind && result.error==other.error,"key failure diagnostics")','require(mem.arena_mark(&arena)==3,"mutable key rollback")','}']
lines[-1:-1] = [edge_source, *key_edges, '_=io.println(io.stdout(),"JSON READ PASS")']
(P/'main.dyn').write_text('\n'.join(lines)+'\n')
for name,flags in [('debug',[]),('release',['--release'])]:
 binary=W/('proof-'+name);p=subprocess.run([str(DYN),'build',str(P),'--no-cache','--quiet','--output',str(binary),*flags],env=env,capture_output=True,timeout=120);assert p.returncode==0,p.stderr.decode();p=subprocess.run([str(binary)],capture_output=True,timeout=30);assert p.returncode==0 and p.stdout==b'JSON READ PASS\n',(name,p.returncode,p.stdout,p.stderr);print('PASS JSON read',name,len(values),'independent trees,',len(invalid),'invalids, numeric/iterator/ownership/alignment/growth/depth checks',flush=True)

# Required arena storage follows the ordinary panic contract, including peak
# growth capacity rather than just the final retained tree size.
for raw,size in [(b'{"a":0}',56),(b'[0,1,2,3,4,5]',16)]:
 (P/'main.dyn').write_text('use "std/encoding/json/read" json\nuse "std/mem" mem\nfn main() { backing:['+str(size)+']u8=[] arena:=mem.arena_from_buffer(backing[..]) _=json.parse(&arena,'+quote(raw)+') }\n')
 for name,flags in [('debug',[]),('release',['--release'])]:
  binary=W/('panic-'+name);subprocess.run([str(DYN),'build',str(P),'--no-cache','--quiet','--output',str(binary),*flags],env=env,check=True,timeout=120)
  result=subprocess.run([str(binary)],capture_output=True,timeout=10);assert result.returncode==101,(name,result.returncode,result.stderr)
print('PASS JSON read arena exhaustion and peak-capacity panics')
if '--cross' in sys.argv:
 import ast,shlex,shutil,signal,re
 def helpers(name):
  tree=ast.parse((R/'tests'/name).read_text());ns=dict(struct=struct)
  exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),name,'exec'),ns)
  return ns
 arm=helpers('thumb-soft.py');rv=helpers('rv32-soft.py')
 cross_source=r'''use "std/encoding/json/read" json
use "std/mem" mem
use "std/io"
pub fn json_read_selected_kind(v:*const json.Value) u8 { return json.kind(v) }
fn require(ok:bool) { if !ok { #panic("JSON read target") } }
fn main() {
 backing:[8192]u8=[] arena:=mem.arena_from_buffer(backing[..])
 require(#sizeof(json.Value)==16 && json_read_selected_kind(nil)==json.KindMissing)
 document:=json.parse(&arena,"{\"\":[0,true,\"a\\u0000b\"],\"utf\":\"caf\\u00e9\",\"i\":-9223372036854775808,\"u\":18446744073709551615,\"real\":1.25}")
 require(document.ok)
 root:=document.root
 require(json.as_i64(json.get(root,"i"))==-9223372036854775807-1)
 require(json.as_u64(json.get(root,"u"))==18446744073709551615)
 require(#bitcast(u64,json.as_f64(json.get(root,"real")))==4608308318706860032)
 require(mem.equal(json.as_text(json.get(root,"utf")),"caf\xc3\xa9"))
 it:=json.iterator(json.get(root,""))
 require(json.next(&it).ok && json.as_bool(json.next(&it).value))
 item:=json.next(&it)
 require(item.ok && mem.equal(json.as_text(item.value),"a\x00b") && !json.next(&it).ok)
 mem.arena_reset(&arena)
 zero:=json.parse(&arena,"-0")
 require(zero.ok && #bitcast(u64,json.as_f64(zero.root))==9223372036854775808)
 mem.arena_reset(&arena)
 mark:=mem.arena_mark(&arena)
 bad:=json.parse(&arena,"[1,]")
 require(!bad.ok && json.is_missing(bad.root) && mem.arena_mark(&arena)==mark)
 require(!json.parse(&arena,"1e9999").ok && mem.arena_mark(&arena)==mark)
 _=io.println(io.stdout(),"JSON READ TARGET PASS")
}
'''
 (P/'main.dyn').write_text(cross_source)
 for arch,variable,program in [('riscv32','DYN_QEMU_RISCV32','qemu-system-riscv32'),('thumbv7em','DYN_QEMU_ARM','qemu-system-arm')]:
  qemu=shlex.split(os.environ.get(variable,'')) or [shutil.which(program) or program]
  if not shutil.which(qemu[0]):print('SKIP JSON read cross: missing',program);continue
  for soft in (False,True):
   target=arch+'-none'+('-soft' if soft else '')
   for mode in ('debug','release'):
    image=W/(target+'-'+mode+'.elf')
    build=subprocess.run([str(DYN),'build',str(P),'--target',target,'--'+mode,'--no-cache','--quiet','--opt-remarks','--output',str(image)],env=env,capture_output=True,text=True,timeout=180)
    assert build.returncode==0,build.stdout+build.stderr
    if mode=='release':assert re.search(r'^remark: json_read_selected_kind: SSA code generation,',build.stdout+build.stderr,re.M),build.stdout+build.stderr
    if soft:(arm if arch=='thumbv7em' else rv)['check_image'](image)
    board=['-machine','mps2-an500','-semihosting-config','enable=on,target=native'] if arch=='thumbv7em' else ['-machine','virt','-bios','none',*(['-cpu','sifive-e31'] if soft else [])]
    proc=subprocess.Popen([*qemu,*board,'-nographic','-kernel',str(image)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    try:output,_=proc.communicate(timeout=45)
    except subprocess.TimeoutExpired:
     os.killpg(proc.pid,signal.SIGKILL);output,_=proc.communicate(timeout=10);raise AssertionError(('JSON read guest timeout',output[-4096:]))
    assert proc.returncode==0 and output.replace(b'\r\n',b'\n')==b'JSON READ TARGET PASS\n',(target,mode,proc.returncode,output[-4096:])
    print('PASS JSON read target',target,mode,'soft instruction audit='+str(soft),flush=True)
holder.cleanup()
