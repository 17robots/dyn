"""Run exact record-function bytes at controlled RX addresses; no product patch."""
from pathlib import Path
import ctypes as C
import os, time, json, statistics, hashlib, struct

W = Path(__file__).resolve().parent
R = W.parents[1]
LIB = R/'build/codegen-followup-20261024/final-kernels.so'
INPUT = R/'build/json-language-isolation-20261024/records.bin'
os.sched_setaffinity(0, {2})
library = C.CDLL(str(LIB))
original = C.cast(library.records, C.c_void_p).value
code = C.string_at(original, 0x11b)
libc = C.CDLL(None, use_errno=True)
libc.mmap.argtypes = [C.c_void_p, C.c_size_t, C.c_int, C.c_int, C.c_int, C.c_long]
libc.mmap.restype = C.c_void_p
libc.mprotect.argtypes = [C.c_void_p, C.c_size_t, C.c_int]
libc.munmap.argtypes = [C.c_void_p, C.c_size_t]
Function = C.CFUNCTYPE(C.c_uint64, C.c_void_p, C.c_size_t, C.c_size_t)
function = Function(original)
data = INPUT.read_bytes()
source = C.create_string_buffer(data)
expected = 1428570000
offsets = (0x700, 0xe00, 0xf00, 0xf80, 0x1700, 0x1f00, 0x1f80)
regions, variants, proof = [], {'original': function}, {}
try:
    for j, offset in enumerate(offsets):
        for distance in range(0x1000000, 0x40000000, 0x10000):
            base = (original & ~4095) + distance
            address = libc.mmap(base, 0x3000, 3, 0x100022, -1, 0) # FIXED_NOREPLACE, PRIVATE, ANON
            if address == base: break
            assert C.get_errno() == 17, (hex(base), address, C.get_errno())
        else: raise RuntimeError('No nearby unused mapping for controlled placement')
        regions.append(base)
        target = base + offset
        relocated = bytearray(code)
        delta = target-original
        for stub in (0xcf, 0xe2, 0xf5, 0x108):
            assert code[stub:stub+3] == b'\x48\x8d\x3d' and code[stub+12] == 0xe8
            for disp in (stub+3, stub+13):
                old = struct.unpack_from('<i', code, disp)[0]
                struct.pack_into('<i', relocated, disp, old-delta)
        assert relocated[:0xcf] == code[:0xcf]
        C.memmove(target, bytes(relocated), len(relocated))
        assert libc.mprotect(base, 0x3000, 5) == 0
        name = hex(offset)
        variants[name] = Function(target)
        proof[name] = {'address': hex(target), 'hot_body_start': hex(target+0x65), 'hot_body_end': hex(target+0xaa), 'crosses_4k': (target+0x65)//4096 != (target+0xa9)//4096}
    samples = {n: [] for n in variants}
    for rep in range(33):
        order = list(variants)
        order = order[rep%len(order):]+order[:rep%len(order)]
        if rep%2: order.reverse()
        for name in order:
            start = time.perf_counter_ns()
            result = variants[name](source, len(data), 20)
            elapsed = (time.perf_counter_ns()-start)/1e6
            assert result == expected, (name, result)
            if rep >= 2: samples[name].append(elapsed)
    report = {'scope': 'Only exact normal-path code placement changes; cold RIP-relative pointers/calls relocated. Matching cache-line offsets; page boundary is one placement factor, not uniquely isolated.', 'library_sha256': hashlib.sha256(LIB.read_bytes()).hexdigest(), 'normal_code_sha256': hashlib.sha256(code[:0xcf]).hexdigest(), 'original': hex(original), 'placements': proof, 'samples_ms': samples, 'median_ms': {n: statistics.median(s) for n,s in samples.items()}}
    (W/'record-layout-control.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['median_ms'], indent=2), flush=True)
finally:
    for base in regions: libc.munmap(base, 0x3000)
