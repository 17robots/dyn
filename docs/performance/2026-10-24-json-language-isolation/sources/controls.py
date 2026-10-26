from pathlib import Path
import ctypes as C,random,json,struct
W=Path(__file__).resolve().parent;r=random.Random(20261024);libs={n:C.CDLL(str(W/(n+'.so'))) for n in ('dyn','dyn-wrap','c','c-scalar','c-checked')};checks=0
for name,lib in libs.items():
 for symbol in ('scan','integers','records'):
  f=getattr(lib,symbol);f.argtypes=[C.c_void_p,C.c_size_t,C.c_size_t];f.restype=C.c_uint64
 for i in range(100):
  data=bytes(range(256)) if i==0 else r.randbytes(r.randrange(1,4096));buf=C.create_string_buffer(data);want=sum(b in (34,92) or b<32 for b in data)*3;assert lib.scan(buf,len(data),3)==want;checks+=1
  values=[r.randrange(1000000) for _ in range(r.randrange(1,100))];data=(' / '.join(map(str,values))).encode();buf=C.create_string_buffer(data);assert lib.integers(buf,len(data),3)==sum(values)*3;checks+=1
  pairs=[(r.randrange(7),r.randrange(1000000)) for _ in range(r.randrange(1,100))];data=b''.join(struct.pack('<QQ',*v) for v in pairs);buf=C.create_string_buffer(data);assert lib.records(buf,len(data),3)==sum(v for k,v in pairs if k==3)*3;checks+=1
 for data,want in [(b'18446744073709551615',2**64-1),(b'18446744073709551616',0),(b'9999999999999999999999',0)]:
  buf=C.create_string_buffer(data);assert lib.integers(buf,len(data),1)==want;checks+=1
for name in ('dyn-driver','c-driver'):
 lib=C.CDLL(str(W/(name+'.so')));lib.initialize.restype=C.c_uint64;assert lib.initialize()==1
 f=lib.parse_one;f.argtypes=[C.c_void_p,C.c_size_t,C.c_size_t];f.restype=C.c_uint64
 for data,want in [(b'{"x":1,"x":2}',2),(b'[1,2,3]',3),(b'{"a":{"b":true}}',1),(b'[[[',0),(b'{"bad":}',0)]:
  buf=C.create_string_buffer(data);assert f(buf,len(data),0)==want;checks+=1
 lib.destroy()
(W/'controls.json').write_text(json.dumps({'checks_passed':checks,'seed':20261024})+'\n');print(checks,'independent kernel/driver controls passed')
