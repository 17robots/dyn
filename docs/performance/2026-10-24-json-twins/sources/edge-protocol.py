from pathlib import Path
import ctypes as C,json
W=Path(__file__).resolve().parent
class Value(C.Structure):_fields_=[('tag',C.c_uint64),('bits',C.c_uint64)]
class Arena(C.Structure):_fields_=[('data',C.POINTER(C.c_ubyte)),('capacity',C.c_size_t),('offset',C.c_size_t),('peak',C.c_size_t),('allocations',C.c_uint64),('bytes',C.c_uint64),('trace',C.c_uint64),('flags',C.c_uint64)]
class Result(C.Structure):_fields_=[('root',C.POINTER(Value)),('ok',C.c_uint64),('detail',C.c_uint64),('offset',C.c_size_t),('used',C.c_size_t),('retained',C.c_size_t)]
common=C.CDLL(str(W/'common.so'),mode=C.RTLD_GLOBAL);common.lab_set_mode(1)
cases=[bytes.fromhex(x) for x in json.loads((W/'cases.json').read_text())];checks=0
for name in ('dyn','gcc-checked','clang-checked'):
 lib=C.CDLL(str(W/(name+'.so')));f=lib.twin_parse;f.argtypes=[C.POINTER(Arena),C.POINTER(C.c_ubyte),C.c_size_t,C.POINTER(Result)]
 storage=(C.c_ubyte*(1024*1024))()
 for data in cases:
  b=C.create_string_buffer(data);a=Arena(C.cast(storage,C.POINTER(C.c_ubyte)),len(storage),3,3,0,0,0,0);out=Result();f(C.byref(a),C.cast(b,C.POINTER(C.c_ubyte)),len(data),C.byref(out))
  if not out.ok:assert bool(out.root) and out.root.contents.tag==0 and out.root.contents.bits==0,(name,data)
  checks+=1
 # Source may alias allocated prefix, but not the unused tail.
 for mark,start,ok,detail in [(0,10,0,4),(64,4,1,0)]:
  data=b'{"x":1}';C.memmove(C.addressof(storage)+start,data,len(data));a=Arena(C.cast(storage,C.POINTER(C.c_ubyte)),len(storage),mark,mark,0,0,0,0);out=Result();f(C.byref(a),C.cast(C.addressof(storage)+start,C.POINTER(C.c_ubyte)),len(data),C.byref(out));assert out.ok==ok and out.detail==detail,(name,mark,start,out.ok,out.detail);checks+=1
 print('PASS missing stub and alias boundaries',name,flush=True)
(W/'edge-protocol.json').write_text(json.dumps({'checks':checks,'libraries':['dyn','gcc-checked','clang-checked']},indent=2)+'\n')
