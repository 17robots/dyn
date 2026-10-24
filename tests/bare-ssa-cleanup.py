#!/usr/bin/env python3
"""Protected cleanup: exact traces/status on hard/soft RV32 and Thumb.

ROOT/DYN/CLANG and DYN_QEMU_RISCV32/ARM override tools. TMPDIR is respected
and removed on failure/success; container wrappers must mount it identically
and bound their own guest lifetime. Host guests: 10 seconds, 64 KiB combined
output; builds: 120 seconds. No retained experiment files are needed.
52 original fixtures (48 named functions/image), five minimized overlap
fixtures, guards, snapshots, descriptors, and protected durable ABI generators.
This does not replace constructed-graph/sanitizer preflights, host controls,
returning-runtime trap tests, or direct inspection of soft result-bank bytes.
"""
import importlib.util
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()

def mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

b = mod('bare-ssa')
c = mod('bare-ssa-checked')
soft = mod('bare-ssa-soft')
GUEST_SECONDS = 10
OUTPUT_LIMIT = 65536


def run_guest(command, seconds=GUEST_SECONDS):
    """Bound collection itself, including wrappers that exit zero on timeout."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    data = [bytearray(), bytearray()]
    deadline = time.monotonic() + seconds
    reason = None
    try:
        with selectors.DefaultSelector() as selector:
            for i, stream in enumerate((process.stdout, process.stderr)):
                selector.register(stream, selectors.EVENT_READ, i)
            while selector.get_map() or process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = b'BOUND: guest timeout'
                    break
                for key, _ in selector.select(min(.1, max(0, deadline-time.monotonic()))):
                    remaining = OUTPUT_LIMIT - sum(map(len, data))
                    chunk = os.read(key.fileobj.fileno(), min(4096, remaining+1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    data[key.data].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        reason = b'BOUND: output limit'
                        break
                if reason:
                    break
    finally:
        # Kill descendants too: a wrapper may have exited before its guest.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
    out, err = map(bytes, data)
    if reason:
        err += reason
    if reason or any(word in err.lower() for word in
                     (b'timed out', b'timeout', b'terminating on signal')):
        return 124, out.replace(b'\r\n', b'\n'), err
    return process.returncode, out.replace(b'\r\n', b'\n'), err


def guest_controls():
    for diagnostic in ('timed out', 'timeout', 'terminating on signal 15'):
        result = run_guest([sys.executable, '-c',
            f'import sys; sys.stderr.write({diagnostic!r})'])
        assert result[0] == 124, result
    result = run_guest([sys.executable, '-c',
        'import os; data=b"x"*4096\nwhile True: os.write(1,data)'])
    assert result[0] == 124 and len(result[1]) <= OUTPUT_LIMIT
    result = run_guest([sys.executable, '-c', 'import time; time.sleep(5)'], .1)
    assert result[0] == 124 and b'guest timeout' in result[2]


def remark_controls(names):
    lines = [f'remark: {name}: SSA code generation, control' for name in names]
    c.check_remarks('\n'.join(lines), 'ssa', names)
    for index, name in enumerate(names):
        try:
            c.check_remarks('\n'.join(lines[:index] + lines[index+1:]), 'ssa', names)
        except AssertionError:
            continue
        raise AssertionError(('missing named SSA remark accepted', name))
    c.check_remarks('', 'tree', names)
    try:
        c.check_remarks('\n'.join(lines), 'tree', names)
    except AssertionError:
        return
    raise AssertionError('tree accepted SSA remarks')


def fixtures():
    source=r'''use "std/io"
    extern fn cpacr() u32
    extern fn opaque() u32
    extern fn touch(p:rawptr)
    extern fn callback(p:fn())
    fn mark(s:[]const u8) { _=io.write_all(io.stdout(),s) }
    pub fn boom() { #panic("BOOM") }
    pub fn inner() { defer mark("I\n")
    boom() }
    pub fn outer() { defer mark("O\n")
    inner() }
    pub fn indirect(p:fn()) { defer mark("D\n")
    p() }
    pub fn acrossc() { defer mark("C\n")
    callback(boom) }
    pub fn recur(n:u32) { defer mark("R\n")
    if n==0 { boom() }
    recur(n-1) }
    pub fn repeated(n:u32) { defer mark("END\n")
    i:u32=0
    for i<n { _=opaque()
    i+=1 }
    boom() }
    pub fn looped() { i:u32=0
    for i<3 { defer mark("L\n")
    i+=1
    _=opaque() }
    mark("DONE\n") }
    pub fn nested() { defer mark("A\n")
    if opaque()!=0 { defer mark("B\n")
    _=opaque() }
    mark("M\n") }
    pub fn early(n:u32) u64 { defer mark("E\n")
    if n!=0 { defer mark("F\n")
    return 0x1122334455667788 }
    return 3 }
    pub fn capture() { s:[]const u8="OLD\n"
    defer mark(s)
    s="NEW\n"
    mark(s) }
    struct Big { a:u64,b:u64,c:u64 }
    fn show(x:Big) { if x.a!=0x1122334455667788 || x.c!=33 { #panic("capture bad") }
    mark("BIG\n") }
    pub fn captureagg() { x:=Big{a:0x1122334455667788,b:22,c:33}
    defer show(x)
    x.a=1
    x.c=2 }
    pub fn captureindirect() { p:=mark
    s:[]const u8="CAP\n"
    defer p(s)
    p=other
    s="NO\n" }
    fn other(s:[]const u8) { mark("WRONG\n") }
    pub fn snapshot() Big { x:=Big{a:0x1122334455667788,b:22,c:33}
    defer { x.a=0
    x.c=0
    mark("SNAP\n") }
    return x }
    pub fn largeland(n:u32) { a:[2048]u64=[]
    a[2047]=0x1122334455667788
    touch(&a)
    x:u64=5
    if n!=0 { x=0x1122334455667788 }
    defer { if x!=0x1122334455667788 || a[2047]!=0x1122334455667788 { #panic("landing bad") }
    mark("FRAME\n") }
    boom() }
    pub fn repanic() { defer mark("NEVER\n")
    defer { #panic("SECOND") }
    boom() }
    pub fn owned() { a:[4]u8=[79,76,68,10]
    defer { a[0]=88
    a[1]=88
    a[2]=88
    mark("MUTATE\n") }
    #panic(a[0..4]) }
    '''
    cases=[('outer','outer()',101,b'I\nO\nBOOM\n'),('indirect','indirect(boom)',101,b'D\nBOOM\n'),('callback','acrossc()',101,b'C\nBOOM\n'),('recur','recur(3)',101,b'R\n'*4+b'BOOM\n'),('repeated','repeated(100)',101,b'END\nBOOM\n'),('looped','looped()',0,b'L\n'*3+b'DONE\n'),('nested','nested()',0,b'B\nM\nA\n'),('early','if early(1)!=0x1122334455667788 { #panic("return") }',0,b'F\nE\n'),('capture','capture()\ncaptureagg()\ncaptureindirect()',0,b'NEW\nOLD\nBIG\nCAP\n'),('snapshot','x:=snapshot()\nif x.a!=0x1122334455667788 || x.c!=33 { #panic("snapshot") }',0,b'SNAP\n'),('largeland','largeland(opaque())',101,b'FRAME\nBOOM\n'),('repanic','repanic()',101,b'SECOND\n'),('owned','owned()',101,b'MUTATE\nOLD\n\n')]
    # Exercise every arithmetic failure with a pending defer, including both
    # high-product overflow and successful boundary products.
    for ty in ['u64','i64','u32','i32','u8','i8']:
     for op,sym in [('add','+'),('sub','-'),('mul','*'),('div','/'),('rem','%')]:
      name=op+'_'+ty
      source+=f'pub fn {name}(a:{ty},b:{ty}) {ty} {{ defer mark("CHECK\\n")\nreturn a{sym}b }}\n'
      bits=int(ty[1:]);sign=ty[0]=='i';mx=2**(bits-sign)-1;mn=-2**(bits-1) if sign else 0
      a,v=(mx,2) if op=='mul' else (mx,1) if op=='add' else (mn,1) if op=='sub' else (1,0)
      pred='divide.ok' if op in ('div','rem') else 'overflow.ok'
      cases.append((name,f'_={name}({a},{v})',101,f'CHECK\nruntime check failed ({pred}) in {name}\n'.encode()))
      if sign and op in ('div','rem'):
       cases.append((name+'min',f'_={name}({mn},-1)',101,f'CHECK\nruntime check failed (division.overflow.ok) in {name}\n'.encode()))
    source+='pub fn shift(a:u64,b:u64) u64 { defer mark("CHECK\\n")\nreturn a<<b }\n'
    cases += [('shiftcount','_=shift(1,64)',101,b'CHECK\nruntime check failed (shift.count.ok) in shift\n'),('shiftbits','_=shift(18446744073709551615,1)',101,b'CHECK\nruntime check failed (overflow.ok) in shift\n'),('mulbounds','if mul_i64(-9223372036854775808,1)!=-9223372036854775808 || mul_u64(18446744073709551615,1)!=18446744073709551615 || mul_i64(-3,-7)!=21 || mul_u64(0,18446744073709551615)!=0 { #panic("multiply") }',0,b'CHECK\n'*4)]
    assert len(cases) == 52 and len(re.findall(r"pub fn (\w+)", source)) == 48
    groups = [("cleanup", source, cases)]
    original = source
    source = original
    source=r'''use "std/io"
    extern fn opaque() u32
    extern fn cpacr() u32
    fn mark(s:[]const u8) { _=io.write_all(io.stdout(),s) }
    pub fn adjacent() { defer mark("FIRST\n")
    defer mark("SECOND\n") }
    pub fn nested() { defer mark("A\n")
    if opaque()!=0 { defer mark("B\n")
    _=opaque() }
    mark("M\n") }
    pub fn early(n:u32) u64 { defer mark("E\n")
    if n!=0 { defer mark("F\n")
    return 0x1122334455667788 }
    return 3 }
    pub fn overflow(a:u64) u64 { defer mark("CHECK\n")
    return a+1 }
    pub fn lengths() { s:[]const u8="ORIGINAL\n"
    defer mark(s)
    s="X\n"
    i:u32=0
    for i<3 { defer mark(s)
    _=opaque()
    s="LONGER\n"
    i+=1 }
    mark(s) }
    '''
    cases=[('adjacent','adjacent()',0,b'SECOND\nFIRST\n'),('nested','nested()',0,b'B\nM\nA\n'),('early','if early(1)!=0x1122334455667788 { #panic("return") }',0,b'F\nE\n'),('overflow','_=overflow(18446744073709551615)',101,b'CHECK\nruntime check failed (overflow.ok) in overflow\n'),('lengths','lengths()',0,b'X\nLONGER\nLONGER\nLONGER\nORIGINAL\n')]
    groups.append(('minimal', source, cases))
    source = original
    source+=r'''
    pub fn nullcall(p:fn()) { defer mark("CHECK\n")
    p() }
    pub fn index(a:[]const u8,n:usize) u8 { defer mark("CHECK\n")
    return a[n] }
    pub fn slicing(a:[]const u8,l:usize,h:usize) []const u8 { defer mark("CHECK\n")
    return a[l..h] }
    fn highcheck(x:f64,y:u64) { if x!=123456789.25 || y!=0xdeadbeef87654321 { #panic("BANK") }
    mark("BANK\n") }
    pub fn bank(x:f64,y:u64) { defer highcheck(x,y)
    _=opaque()
    boom() }
    '''
    cases=[('nullcall','nullcall(#cast(fn(),#cast(rawptr,0)))',101,b'CHECK\nruntime check failed (function.nonnull.ok) in nullcall\n'),('index','_=index("abc",4)',101,b'CHECK\nruntime check failed (index.ok) in index\n'),('sliceorder','_=slicing("abc",2,1)',101,b'CHECK\nruntime check failed (slice.order.ok) in slicing\n'),('slicebounds','_=slicing("abc",0,4)',101,b'CHECK\nruntime check failed (slice.bounds.ok) in slicing\n'),('bank','bank(123456789.25,0xdeadbeef87654321)',101,b'BANK\nBOOM\n')]
    groups.append(('guards', source, cases))
    source = original
    source+=r'''
    pub fn deref(p:*u64) u64 { defer mark("CHECK\n")
    return p.* }
    
    pub fn nullcall(p:fn()) { defer mark("CHECK\n")
    p() }
    pub fn index(a:[]const u8,n:usize) u8 { defer mark("CHECK\n")
    return a[n] }
    pub fn slicing(a:[]const u8,l:usize,h:usize) []const u8 { defer mark("CHECK\n")
    return a[l..h] }
    fn highcheck(x:f64,y:u64) { if x!=123456789.25 || y!=0xdeadbeef87654321 { #panic("BANK") }
    mark("BANK\n") }
    pub fn bank(x:f64,y:u64) { defer highcheck(x,y)
    _=opaque()
    boom() }
    '''
    cases=[('nonnull','_=deref(nil)',101,b'CHECK\nruntime check failed (pointer.nonnull.ok) in deref\n'),('aligned','_=deref(#cast(*u64,1))',101,b'CHECK\nruntime check failed (pointer.aligned.ok) in deref\n')]
    groups.append(('pointer-guards', source, cases))
    source = original
    source+=r'''
    pub fn scalarshot(x:u64) u64 { defer { x=1
    mark("S\n") }
    return x }
    pub fn descshot(x:[]const u8) []const u8 { defer { x="WRONG"
    mark("D\n") }
    return x }
    '''
    cases=[('scalarshot','if scalarshot(0xdeadbeef87654321)!=0xdeadbeef87654321 { #panic("scalar snapshot") }',0,b'S\n'),('descshot',r'mark(descshot("ORIGINAL\n"))',0,b'D\nORIGINAL\n')]
    groups.append(('snapshots', source, cases))
    source = original
    source=r'''use "std/io"
    extern fn cpacr() u32
    fn mark(s:[]const u8) { _=io.write_all(io.stdout(),s) }
    fn checkany(x:any) { case x { is u64 n => { if n!=0x1122334455667788 { #panic("any") }
    mark("ANY\n") } _ => { #panic("type") } } }
    fn mutable(x:[]u8) { if #len(x)!=3 || x[2]!=67 { #panic("slice") }
    mark("SLICE\n") }
    fn scalar(x:u64) { if x!=0xdeadbeef87654321 { #panic("scalar") }
    mark("SCALAR\n") }
    pub fn controls() { a:[3]u8=[65,66,67]
    n:u64=0x1122334455667788
    defer mark("LITERAL\n")
    defer checkany(n)
    defer mutable(a[0..3])
    defer scalar(0xdeadbeef87654321) }
    '''
    cases=[('controls','controls()',0,b'SCALAR\nSLICE\nANY\nLITERAL\n')]
    groups.append(('descriptors', source, cases))
    return groups


CLEAN = '''void clean(unsigned long long x){if(x!=0x1122334455667788ULL)__builtin_trap();}
unsigned cpacr(void){
#ifdef __arm__
return *(volatile unsigned*)0xe000ed88;
#else
return 0;
#endif
}
'''
ORACLE = '''unsigned opaque(void){return 1;}
void touch(void*p){__asm__ volatile(""::"r"(p):"memory");}
__attribute__((noinline)) void callback(void(*p)(void)){
volatile unsigned a[40];a[0]=1;p();a[39]=a[0];}
''' + CLEAN


def abi_fixtures():
    # Reuse durable generators; identity/byte comparisons need no soft C FP runtime.
    aggregate = soft.aggregate_generator()
    varargs = mod('bare-ssa-varargs')
    for label, source, oracle, names, expected in (
        ('aggregate-abi', aggregate['source'], aggregate['c'], aggregate['names'], b'ABI OK\n'),
        ('varargs-abi', varargs.src, varargs.c, varargs.names, b'VARARGS OK\n'),
    ):
        source = 'extern fn clean(x:u64)\n' + re.sub(
            r'(pub fn [^\n{]+\{)', r'\1 defer clean(0x1122334455667788)\n', source)
        if label == 'aggregate-abi':
            # Destructive cleanup proves the return is a snapshot across ABI shapes.
            source, count = re.subn(
                r'(pub fn id\w+\(x:[^)]+\) \w+ \{) defer clean\(0x1122334455667788\)\n',
                r'\1 defer { x.a=x.a+x.a\nclean(0x1122334455667788) }\n', source)
            assert count == 14, count
            source = 'extern fn cpacr() u32\n' + source
            oracle += CLEAN
        else:
            oracle += CLEAN.split('unsigned cpacr')[0]
        assert len(names) == (164 if label == 'aggregate-abi' else 140)
        yield label, source, oracle, names, expected


def build_run(work, source, oracle, names, expected, target, flags, qemu, board, audit):
    work.mkdir()
    (work/'main.dyn').write_text(source)
    (work/'oracle.c').write_text(oracle)
    obj = work/'oracle.o'
    subprocess.run([*b.CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                    '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=120)
    if target.startswith('thumb'):
        b.arm_addends(obj)
    for mode in ('ssa', 'tree'):
        env = dict(os.environ)
        env.pop('DYN_NO_SSA', None)
        if mode == 'tree':
            env['DYN_NO_SSA'] = '1'
        image = work/(mode+'.elf')
        result = subprocess.run([b.DYN, 'build', str(work), '--release', '--target', target,
            '--no-cache', '--opt-remarks', '--output', str(image), '--link', str(obj)],
            env=env, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        assert result.returncode == 0, (target, work.name, mode, log[-8000:])
        c.check_remarks(log, mode, names)
        if audit:
            audit['check_image'](image)
        actual = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
        assert actual == expected, (target, work.name, mode, expected,
                                    actual[0], actual[1][:2000], actual[2][:2000])


def main():
    guest_controls()
    groups = fixtures()
    abis = list(abi_fixtures())
    for _, source, _ in groups:
        remark_controls(re.findall(r'pub fn (\w+)', source))
    for _, _, _, names, _ in abis:
        remark_controls(names)
    if not shutil.which(b.DYN) or not b.CLANG or not shutil.which(b.CLANG[0]):
        print('SKIP cleanup: DYN or CLANG unavailable')
        return
    runs = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        for sf in (False, True):
            t = target + ('-soft' if sf else '')
            rv = target.startswith('riscv')
            ff = flags if not sf else ([f.replace('rv32imafd', 'rv32im').replace('ilp32d', 'ilp32')
                for f in flags] if rv else ['--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=soft'])
            audit = soft.fixture('rv32' if rv else 'thumb')[0] if sf else None
            command = qemu + (['-cpu', 'sifive-e31'] if sf and rv else [])
            check = 'if cpacr() & 0x00f00000 != 0 { #panic("FPU enabled") }\n' if sf and not rv else ''
            with tempfile.TemporaryDirectory(prefix='dyn-cleanup-') as temporary:
                work = Path(temporary)
                for group, source, cases in groups:
                    names = re.findall(r'pub fn (\w+)', source)
                    for name, body, status, trace in cases:
                        build_run(work/(group+'-'+name), source+'fn main() { '+check+body+' }',
                                  ORACLE, names, (status, trace, b''), t, ff, command, board, audit)
                        runs += 2
                    print(f'PASS {t} {group}: {len(cases)*2} exact guests; {len(names)} named SSA assertions/image', flush=True)
                for label, source, oracle, names, trace in abis:
                    source, count = re.subn(r'fn main\(\)\s*\{', lambda m: m[0]+check, source)
                    assert count == 1
                    build_run(work/label, source, oracle, names, (0, trace, b''),
                              t, ff, command, board, audit)
                    runs += 2
                    print(f'PASS {t} {label}: 2 exact guests; {len(names)} named SSA assertions/image', flush=True)
    print(f'{"PASS" if runs else "SKIP"} cleanup: {runs} guests; '
          '10s/64KiB guest limits, 120s builds; missing-remark and bound controls passed', flush=True)


if __name__ == '__main__':
    main()
