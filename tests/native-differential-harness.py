#!/usr/bin/env python3
"""Keep differential qualification finite without accepting unknown outcomes."""
import contextlib
import importlib.util
import io
from pathlib import Path
import random
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_differential', ROOT/'tools/backend/native-differential.py')
diff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diff)

for seed in range(10):
    rng = random.Random(seed)
    for _ in range(100):
        a, b = (str(rng.randrange(1 << 64)) for _ in range(2))
        for name in ('loop_nested', 'loop_forever', 'loop_condition_div', 'generic_recursion'):
            result = diff.bounded_combo(name, ['u64', 'u64'], (a, b))
            assert 0 <= int(result[0]) <= 64 and result[1] == b
        for signed in (False, True):
            ty = 'i64' if signed else 'u64'
            low = -(1 << 63) if signed else 0
            high = (1 << (64 - signed)) - 1
            for start in (low, high, int(a) % (high + 1)):
                result = diff.bounded_combo(f'range_{ty}_1_1', [ty, ty], (str(start), b))
                assert result[0] == str(start)
                assert low <= int(result[1]) <= high and abs(int(result[1]) - start) <= 32
        # Arithmetic and C ABI coverage must retain every full-width argument.
        for name in ('add_u64', 'c_abi_spill', 'c_abi_fp_spill'):
            assert diff.bounded_combo(name, ['u64', 'u64'], (a, b)) == (a, b)
maximum = str((1 << 64) - 1)
assert diff.bounded_combo('range_bound_panic', ['u64', 'u64'], (maximum, '0')) == (maximum, '0')

ok = (0, b'7\n', b'')
timeout = ('timeout', b'', b'')
for native, reference in ((timeout, ok), (ok, timeout), (timeout, timeout), ((0, b'8\n', b''), ok)):
    with patch.object(diff, 'run_cases', return_value=[native]), contextlib.redirect_stdout(io.StringIO()):
        try:
            diff.compare('test', [], Path('unused'), [reference], '.', 1)
        except SystemExit:
            pass
        else:
            raise AssertionError(f'qualification accepted {native!r} against {reference!r}')
with patch.object(diff, 'run_cases', return_value=[ok]), contextlib.redirect_stdout(io.StringIO()):
    diff.compare('test', [], Path('unused'), [ok], '.', 1)
print('PASS differential harness: bounded workloads; full-width ABI inputs; all timeouts fail')
