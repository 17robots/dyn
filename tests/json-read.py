#!/usr/bin/env python3
"""Experimental compact JSON DOM: independent expected trees and ownership edges."""
from pathlib import Path
import json,random,subprocess,os,struct,tempfile,sys
R=Path(__file__).resolve().parents[1];DYN=Path(os.environ.get('DYN',R/'build/dyn-release')).resolve();holder=tempfile.TemporaryDirectory(prefix='dyn-json-read-');W=Path(holder.name);P=W/'proof';P.mkdir();env=dict(os.environ,DYN_SDK=os.environ.get('DYN_SDK',str(R)));rng=random.Random(20261024)
def quote(x):return '"'+''.join('\\x%02x'%b for b in x)+'"'
def check(node,v,label):
 out=[]
 def req(s):out.append('require('+s+','+quote(label.encode())+')')
 if v is None:req('json.kind('+node+')==json.Kind.Null')
 elif isinstance(v,bool):req('json.kind('+node+')==json.Kind.Bool && json.as_bool('+node+')=='+str(v).lower())
 elif isinstance(v,str):req('json.kind('+node+')==json.Kind.String && mem.equal(json.as_text('+node+'),'+quote(v.encode())+')')
 elif isinstance(v,(int,float)):
  bits=struct.unpack('<Q',struct.pack('<d',float(v)))[0];req('json.kind('+node+')==json.Kind.Number && #bitcast(u64,json.as_f64('+node+'))=='+str(bits))
 elif isinstance(v,list):
  req('json.kind('+node+')==json.Kind.Array && json.length('+node+')=='+str(len(v)))
  for i,x in enumerate(v):out+=check('json.at('+node+','+str(i)+')',x,label)
  req('json.kind(json.at('+node+','+str(len(v))+'))==json.Kind.Missing')
 else:
  req('json.kind('+node+')==json.Kind.Object && json.length('+node+')=='+str(len(v)))
  for k,x in v.items():out+=check('json.get('+node+','+quote(k.encode())+')',x,label)
  req('json.kind(json.get('+node+',"not_present_zzz"))==json.Kind.Missing')
 return out
values=[None,True,False,0,-0.0,1,-1,2**64-1,-2**63,2**53-1,1.25,1e300,1e-300,'','ascii','é😀','a\0b\n\\"',{'é😀':'café','a\0b':[True,None]},[],{},[1,2,{'x':'y'}]]
values.append({'é😀':'café','a\0b':[True,None]})
for i in range(60):values.append({'id':i,'key'+str(i):['x'*(i%17),'é😀',i%2==0,None,{'nested':i*19}],'escaped':'a\nb\t"\\'})
MUTABLE='''struct MutableParsed { root: *const mutable.Value, offset: usize, code: u8 }
fn parse_mutable(arena: *mem.Arena, source: []const u8) MutableParsed {
 root := mutable.parse(arena, source) catch err {
  case err {
   .Invalid(at) => { return MutableParsed{ root: &mutable.nil_value, offset: at, code: 1 } }
   .TooLarge(at) => { return MutableParsed{ root: &mutable.nil_value, offset: at, code: 2 } }
   .Unsupported(at) => { return MutableParsed{ root: &mutable.nil_value, offset: at, code: 2 } }
  }
 }
 return MutableParsed{ root: root }
}'''
HELPER='''// code: 0 parsed, 1 Invalid, 2 TooLarge; a failed parse leaves the missing root.
struct Parsed { root: *const json.Value, offset: usize, code: u8 }
fn parse(arena: *mem.Arena, source: []const u8) Parsed {
 root := json.parse(arena, source) catch err {
  case err {
   .Invalid(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 1 } }
   .TooLarge(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 2 } }
   .Unsupported(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 2 } }
  }
 }
 return Parsed{ root: root }
}'''
lines=['use json "std/encoding/json/read"','use mutable "std/encoding/json"','use mem "std/mem"','use "std/io"','fn require(ok:bool,label:[]const u8) { if !ok { #panic(label) } }','fn more(it:*json.Iterator) bool {\n_=json.next(it)\nreturn !it.ended\n}','fn blocks(arena:*const mem.Arena) usize {\ncount:usize=0\nblock:=arena.current\nfor block!=nil {\ncount+=1\nblock=block.previous\n}\nreturn count\n}',HELPER,MUTABLE,'fn main() {','require(#sizeof(json.Value)==16,"compact value size")','arena:=mem.arena_alloc(mem.MiB)\ndefer mem.arena_release(arena)','_=mem.push_bytes(arena,3)\nprefix_mark:=mem.arena_mark(arena)']
for i,v in enumerate(values):
 raw=json.dumps(v,ensure_ascii=i%2==0,separators=(',',':')).encode();lines+=['if true {',f'original:={quote(raw)}','input:=mem.push_bytes(arena,original.len)\n_=mem.copy(input,original)','mark:=mem.arena_mark(arena)','result:=parse(arena,input)','require(result.code==0,"valid metadata")','for i in 0..input.len { input[i]=255 }']
 # errors is not re-exported as Kind; use zero enum via cast.
 lines+=check('result.root',v,'value '+str(i));lines+=['mem.arena_rewind(arena,mark)','mem.arena_rewind(arena,prefix_mark)','}']
invalid=[b'',b' ',b'01',b'1.',b'1e',b'-',b'true false',b'"x" trailing',b'{"a":}',b'[1,]',b'{"a" 1}',b'"unterminated',b'"bad\\q"',b'"bad\\"',b'"\\u12"',b'"\\u00xz"',b'"\\ud800"',b'"\\udc00"',b'"\\ud800\\u0041"',b'"\xc0\xaf"',b'"\xed\xa0\x80"',b'"\xf4\x90\x80\x80"',b'"\xe2\x82"',b'"\x80"',b'['*257+b'0'+b']'*257,b'1e9999']+[b'"a'+bytes([x])+b'b"' for x in range(32)]
invalid += [b'['*n for n in range(1,258)] + [b'{\"x\":'*n for n in range(1,65)]
for i,raw in enumerate(invalid):lines+=['if true {',f'result:=parse(arena,{quote(raw)})','require(result.code!=0 && json.kind(result.root)==json.Kind.Missing && mem.arena_mark(arena)==prefix_mark,"invalid rollback")','}']
large=json.dumps(list(range(1000)),separators=(',',':')).encode();deep=b'['*256+b'0'+b']'*256
lines += ['if true {',f'result:=parse(arena,{quote(large)})','require(result.code==0 && json.length(result.root)==1000,"growth array")','for i in 0..1000 { require(json.as_f64(json.at(result.root,i))==#cast(f64,i),"contiguous growth") }','require(result.root.bits==1001,"subtree span")','mem.arena_rewind(arena,prefix_mark)','}',f'require(parse(arena,{quote(deep)}).code==0,"depth 256")','mem.arena_rewind(arena,prefix_mark)','if true {','backing:[512]u8\nfixed:=mem.arena_from_buffer(backing[..])','result:=parse(fixed,"{\\"x\\":1}")','require(result.code==0 && json.as_f64(json.get(result.root,"x"))==1.0,"fixed buffer")','}', 'require(json.kind(nil)==json.Kind.Missing && json.kind(json.get(nil,"x"))==json.Kind.Missing,"nil navigation")','}']
edge_source = r'''
if true {
  value:=parse(arena,"-0")
  require(value.code==0 && #bitcast(u64,json.as_f64(value.root))==9223372036854775808,"negative integer zero")
  mem.arena_rewind(arena,prefix_mark)
}
if true {
  value:=parse(arena,"{\"\":1,\"dup\":2,\"dup\":3}")
  require(value.code==0 && json.as_u64(json.get(value.root,""))==1 && json.as_u64(json.get(value.root,"dup"))==2,"empty and duplicate keys")
  it:=json.iterator(value.root)
  require(more(&it) && more(&it) && more(&it) && !more(&it),"object iterator count")
  mem.arena_rewind(arena,prefix_mark)
}
if true {
  value:=parse(arena,"18446744073709551615")
  require(value.code==0 && json.as_u64(value.root)==18446744073709551615 && json.as_i64(value.root)==0,"unsigned maximum")
  mem.arena_rewind(arena,prefix_mark)
  value=parse(arena,"-9223372036854775808")
  require(value.code==0 && json.as_i64(value.root)==-9223372036854775807-1 && json.as_u64(value.root)==0,"signed minimum")
  mem.arena_rewind(arena,prefix_mark)
  value=parse(arena,"-1e9999")
  require(value.code!=0 && value.code == 2,"real negative overflow")
  require(mem.arena_mark(arena)==prefix_mark,"real overflow rollback")
}
for pad in 0..16 {
  backing:[4096]u8
  fixed:=mem.arena_from_buffer(backing[pad..])
  result:=parse(fixed,"{\"x\":[0,true,\"a\\u0000b\"],\"y\":-1.25}")
  require(result.code==0 && (#cast(usize,result.root)&7)==0,"misaligned backing")
  require(json.length(json.get(result.root,"x"))==3 && json.as_f64(json.get(result.root,"y"))==-1.25,"misaligned values")
  it:=json.iterator(json.get(result.root,"x"))
  require(json.as_u64(json.next(&it).value)==0 && json.as_bool(json.next(&it).value),"array iterator")
  item:=json.next(&it)
  require(!it.ended && mem.equal(json.as_text(item.value),"a\x00b") && !more(&it),"iterator decoded bytes")
}
if true {
  backing:[80+mem.ArenaBufferOverhead]u8
  pad:=(16-(#cast(usize,&backing[0])&15))&15
  fixed:=mem.arena_from_buffer(backing[pad..pad+mem.ArenaHeader+80])
  result:=parse(fixed,"\"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\"")
  require(result.code==0 && mem.arena_used(fixed)==80,"scalar exact capacity")
}
'''
# Keys and scalar values remain permitted at the maximum container depth.
# This specifically protects direct key dispatch from acquiring a container
# depth check, and compares malformed key offsets against the mutable parser.
key_edges=[]
for scalar,kind in [(b'""','String'),(b'"value"','String'),(b'null','Null'),(b'true','Bool'),(b'42','Number')]:
 raw=b'['*255+b'{"\\u006b":'+scalar+b'}'+b']'*255
 key_edges += ['if true {',f'raw:={quote(raw)}','result:=parse(arena,raw)','require(result.code==0,"maximum-depth object key and scalar")','node:=result.root','for depth in 0..255 { node=json.at(node,0) }',f'require(json.kind(json.get(node,"k"))==json.Kind.{kind},"maximum-depth scalar kind")','mem.arena_rewind(arena,prefix_mark)','other:=parse_mutable(arena,raw)','require(other.code==0,"mutable maximum-depth control")','mem.arena_rewind(arena,prefix_mark)','}']
for raw in [b'{"\\q":0}',b'{"\\ud800":0}',b'{"\\u006b" 0}',b'['*255+b'{"\\q":0}'+b']'*255,b'['*256+b'{"k":0}'+b']'*256]:
 key_edges += ['if true {',f'raw:={quote(raw)}','result:=parse(arena,raw)','require(result.code!=0 && json.is_missing(result.root) && mem.arena_mark(arena)==prefix_mark,"key failure rollback")','other:=parse_mutable(arena,raw)','require(other.code!=0 && result.offset==other.offset && result.code==other.code,"key failure diagnostics")','require(mem.arena_mark(arena)==prefix_mark,"mutable key rollback")','}']
# Small blocks exercise tape relocation and virtual marks, including arenas
# already on a later block before parsing. Relative tape spans must survive copies.
chain_objects = [{'name': 'item '+str(i), 'escaped': 'a\nb\t"\\é😀',
                  'nested': [i, {'last': i*13}]} for i in range(80)]
chain_raw = json.dumps(chain_objects,ensure_ascii=True,separators=(',',':')).encode()
chain_source = [
 'for block_size in [256,512] {',
 'for bounded in [false,true] {',
 'for preforced in [false,true] {',
 'chain: *mem.Arena = nil',
 'blocks_from:=mem.pages(0)\nif bounded { blocks_from.limit=256*mem.KiB }\nblocks_from.block_size=#cast(usize,block_size)\nchain=mem.arena_from_source(blocks_from)',
 'prefix:=mem.push_array<u8>(chain, 8)',
 'mem.fill(prefix,91)',
 'if preforced { _=mem.push_bytes(chain,512)\n_=mem.push_bytes(chain,8)\nrequire(blocks(chain)>1,"pre-forced chain") }',
 'saved_mark:=mem.arena_mark(chain)',
 'saved_blocks:=blocks(chain)\nsaved_backing:=chain.backing',
 f'large:=parse(chain,{quote(large)})',
 'require(large.code==0 && json.length(large.root)==1000 && large.root.bits==1001,"chained large tape")',
 'for i in 0..1000 { require(json.as_u64(json.at(large.root,i))==#cast(u64,i),"chained tape relocation values") }',
 'require(blocks(chain)>saved_blocks,"parser added blocks")',
 'mem.arena_rewind(chain,saved_mark)',
 'require(mem.arena_mark(chain)==saved_mark && blocks(chain)==saved_blocks && chain.backing==saved_backing,"chained success rewind")',
 f'input_data: [{len(chain_raw)}]u8 = [{",".join(map(str,chain_raw))}]',
 'owned:=parse(chain,input_data[..])',
 'require(owned.code==0,"chained object document")',
 'mem.fill(input_data[..],255)',
 'it:=json.iterator(owned.root)',
 'for i in 0..80 { entry:=json.next(&it)\nrequire(!it.ended && json.as_u64(json.at(json.get(entry.value,"nested"),0))==#cast(u64,i),"chained iterator subtree") }',
 'require(!more(&it),"chained iterator end")',
 *check('owned.root', chain_objects, 'chained object/string ownership'),
 'mem.arena_rewind(chain,saved_mark)',
 f'bad:=parse(chain,{quote(b"["*257+b"0"+b"]"*257)})',
 'require(bad.code!=0 && json.is_missing(bad.root) && mem.arena_mark(chain)==saved_mark && blocks(chain)==saved_blocks && chain.backing==saved_backing,"chained failure rollback")',
 'for byte in prefix { require(byte==91,"chained prefix canary") }',
 'mem.arena_release(chain)',
 'chain=nil',
 '}', '}', '}'
]

lines[-1:-1] = [edge_source, *key_edges, *chain_source, 'io.println("JSON READ PASS")']
(P/'main.dyn').write_text('\n'.join(lines)+'\n')
for name,flags in [('debug',[]),('release',['--release'])]:
 binary=W/('proof-'+name);p=subprocess.run([str(DYN),'build',str(P),'--no-cache','--quiet','--output',str(binary),*flags],env=env,capture_output=True,timeout=120);assert p.returncode==0,p.stderr.decode();p=subprocess.run([str(binary)],capture_output=True,timeout=30);assert p.returncode==0 and p.stdout==b'JSON READ PASS\n',(name,p.returncode,p.stdout,p.stderr);print('PASS JSON read',name,len(values),'independent trees,',len(invalid),'invalids, numeric/iterator/ownership/alignment/growth/depth checks',flush=True)

# Required arena storage follows the ordinary panic contract, including peak
# growth capacity rather than just the final retained tree size.
for raw,size in [(b'{"a":0}',56),(b'[0,1,2,3,4,5]',16)]:
 (P/'main.dyn').write_text('use json "std/encoding/json/read"\nuse mem "std/mem"\nfn main() {\nbacking:['+str(size)+'+mem.ArenaBufferOverhead]u8\npad:=(16-(#cast(usize,&backing[0])&15))&15\narena:=mem.arena_from_buffer(backing[pad..pad+mem.ArenaHeader+'+str(size)+'])\n_=json.parse(arena,'+quote(raw)+') catch { return }\n}\n')
 for name,flags in [('debug',[]),('release',['--release'])]:
  binary=W/('panic-'+name);subprocess.run([str(DYN),'build',str(P),'--no-cache','--quiet','--output',str(binary),*flags],env=env,check=True,timeout=120)
  result=subprocess.run([str(binary)],capture_output=True,timeout=10);assert result.returncode==101 and b'arena exhausted' in result.stderr,(name,result.returncode,result.stderr)
# Input in the arena's free space is a caller bug: parse panics.
(P/'main.dyn').write_text('use json "std/encoding/json/read"\nuse mem "std/mem"\nfn main() {\nstorage:[1024]u8\nfixed:=mem.arena_from_buffer(storage[..])\ninput:=fixed.data[mem.ArenaHeader+10..mem.ArenaHeader+20]\n_=mem.copy(input,"[1,2,3,4] ")\n_=json.parse(fixed,input) catch { return }\n}\n')
for name,flags in [('debug',[]),('release',['--release'])]:
 binary=W/('alias-'+name);subprocess.run([str(DYN),'build',str(P),'--no-cache','--quiet','--output',str(binary),*flags],env=env,check=True,timeout=120)
 result=subprocess.run([str(binary)],capture_output=True,timeout=10);assert result.returncode!=0 and b'overlaps arena output' in result.stderr,(name,result.returncode,result.stderr)
print('PASS JSON read arena exhaustion, peak-capacity and alias panics')
if '--cross' in sys.argv:
 import ast,shlex,shutil,signal,re
 def helpers(name):
  tree=ast.parse((R/'tests'/name).read_text());ns=dict(struct=struct)
  exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]),name,'exec'),ns)
  return ns
 arm=helpers('thumb-soft.py');rv=helpers('rv32-soft.py')
 cross_source=r'''use json "std/encoding/json/read"
use io "std/io"
use mem "std/mem"
// code: 0 parsed, 1 Invalid, 2 TooLarge; a failed parse leaves the missing root.
struct Parsed { root: *const json.Value, offset: usize, code: u8 }
fn parse(arena: *mem.Arena, source: []const u8) Parsed {
 root := json.parse(arena, source) catch err {
  case err {
   .Invalid(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 1 } }
   .TooLarge(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 2 } }
   .Unsupported(at) => { return Parsed{ root: &json.nil_value, offset: at, code: 2 } }
  }
 }
 return Parsed{ root: root }
}
pub fn json_read_selected_kind(v:*const json.Value) u8 { return json.kind(v) }
fn require(ok:bool) { if !ok { #panic("JSON read target") } }
fn more(it:*json.Iterator) bool {
_=json.next(it)
return !it.ended
}
fn blocks(arena:*const mem.Arena) usize {
  count:usize=0
  block:=arena.current
  for block!=nil {
    count+=1
    block=block.previous
  }
  return count
}
fn main() {
 backing:[8192]u8
 arena:=mem.arena_from_buffer(backing[..])
 require(#sizeof(json.Value)==16 && json_read_selected_kind(nil)==json.Kind.Missing)
 document:=parse(arena,"{\"\":[0,true,\"a\\u0000b\"],\"utf\":\"caf\\u00e9\",\"i\":-9223372036854775808,\"u\":18446744073709551615,\"real\":1.25}")
 require(document.code==0)
 root:=document.root
 require(json.as_i64(json.get(root,"i"))==-9223372036854775807-1)
 require(json.as_u64(json.get(root,"u"))==18446744073709551615)
 require(#bitcast(u64,json.as_f64(json.get(root,"real")))==4608308318706860032)
 require(mem.equal(json.as_text(json.get(root,"utf")),"caf\xc3\xa9"))
 it:=json.iterator(json.get(root,""))
 require(more(&it) && json.as_bool(json.next(&it).value))
 item:=json.next(&it)
 require(!it.ended && mem.equal(json.as_text(item.value),"a\x00b") && !more(&it))
 mem.arena_reset(arena)
 zero:=parse(arena,"-0")
 require(zero.code==0 && #bitcast(u64,json.as_f64(zero.root))==9223372036854775808)
 mem.arena_reset(arena)
 mark:=mem.arena_mark(arena)
 bad:=parse(arena,"[1,]")
 require(bad.code!=0 && json.is_missing(bad.root) && mem.arena_mark(arena)==mark)
 require(parse(arena,"1e9999").code!=0 && mem.arena_mark(arena)==mark)
 io.println("JSON READ TARGET PASS")
}
'''
 cross_chain = '\n'.join([
  'blocks_from:=mem.pages(128*mem.KiB)\nblocks_from.block_size=512\nchain:=mem.arena_from_source(blocks_from)',
  'prefix:=mem.push_array<u8>(chain, 8)',
  'mem.fill(prefix,91)',
  '_=mem.push_bytes(chain,512)',
  '_=mem.push_bytes(chain,8)',
  'before:=mem.arena_mark(chain)',
  'before_blocks:=blocks(chain)',
  f'large:=parse(chain,{quote(large)})',
  'require(large.code==0 && json.length(large.root)==1000 && large.root.bits==1001)',
  'for i in 0..1000 { require(json.as_u64(json.at(large.root,i))==#cast(u64,i)) }',
  'mem.arena_rewind(chain,before)',
  'require(mem.arena_mark(chain)==before && blocks(chain)==before_blocks)',
  'owned:=parse(chain,"{\\"key\\":[\\"a\\\\u0000b\\",{\\"last\\":42}]}")',
  'require(owned.code==0 && json.as_u64(json.get(json.at(json.get(owned.root,"key"),1),"last"))==42)',
  'require(mem.equal(json.as_text(json.at(json.get(owned.root,"key"),0)),"a\\x00b"))',
  'mem.arena_rewind(chain,before)',
  'failed:=parse(chain,"[1,]")',
  'require(failed.code!=0 && mem.arena_mark(chain)==before && blocks(chain)==before_blocks)',
  'for byte in prefix { require(byte==91) }',
  'mem.arena_release(chain)',
  'chain=nil',
 ])
 assert ' io.println("JSON READ TARGET PASS")' in cross_source
 cross_source = cross_source.replace(' io.println("JSON READ TARGET PASS")', cross_chain+'\n io.println("JSON READ TARGET PASS")')
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
