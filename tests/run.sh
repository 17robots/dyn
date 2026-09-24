#!/bin/sh
set -eu

DYN=${DYN:-./build/dyn}

test "$($DYN version)" = "dyn ${DYN_VERSION:-0.1.0-dev}"
test "$($DYN --version)" = "dyn ${DYN_VERSION:-0.1.0-dev}"
$DYN cache stats | grep -q '^cache '
if $DYN cache nope >build/cache-command.out 2>&1; then
  echo "expected invalid cache action" >&2; exit 1
fi
grep -q "cache expects 'stats' or 'clean'" build/cache-command.out
$DYN --help | grep -q '^Dyn compiler'
if $DYN build tests/empty --jobs 0 >build/jobs-error.out 2>&1; then
  echo "expected invalid jobs diagnostic" >&2
  exit 1
fi
grep -q -- '--jobs requires an integer from 1 to 256' build/jobs-error.out
$DYN check tests/empty --quiet --timings 2>build/cli-timings.out
grep -q '^timing load ' build/cli-timings.out
grep -q '^timing check ' build/cli-timings.out
if $DYN check tests/empty --target mips-linux >build/unsupported-target.out 2>&1; then
  echo "expected unsupported target diagnostic" >&2
  exit 1
fi
grep -q "target 'mips-linux' is not implemented; supported targets: x86_64-linux, aarch64-linux, aarch64-macos, x86_64-windows" build/unsupported-target.out
$DYN build tests/empty --target aarch64-linux --output build/aarch64-target-test --no-link --emit-asm
file build/aarch64-target-test.o | grep -q 'ARM aarch64'
$DYN build tests/target-aarch64-syscall --target aarch64-linux --output build/aarch64-syscall-test --no-link --emit-ir --no-cache
grep -q 'i64 64' build/aarch64-syscall-test.ll
mkdir -p build/aarch64-unmapped
printf 'fn main() { _ = #syscall(999) }\n' >build/aarch64-unmapped/main.dyn
if $DYN check build/aarch64-unmapped --target aarch64-linux >build/aarch64-syscall.out 2>&1; then
  echo "expected unmapped AArch64 syscall diagnostic" >&2; exit 1
fi
grep -q "syscall has no AArch64 Linux mapping" build/aarch64-syscall.out
$DYN build tests/target-macos --target aarch64-macos --output build/macos-target-test --no-link --emit-asm --no-cache
file build/macos-target-test.o | grep -q 'Mach-O 64-bit arm64'
$DYN build tests/target-windows --target x86_64-windows --output build/windows-target-test --no-link --emit-asm --no-cache
python3 -c 'from pathlib import Path; assert Path("build/windows-target-test.o").read_bytes()[:2] == bytes.fromhex("6486")' # AMD64 COFF machine ID
$DYN build tests/target-macos --target aarch64-macos --output build/macos-link-test --no-cache
file build/macos-link-test | grep -q 'Mach-O 64-bit arm64 executable'
$DYN build tests/target-windows --target x86_64-windows --output build/windows-link-test --no-cache
file build/windows-link-test | grep -q 'PE32+ executable.*x86-64'
$DYN build tests/target-macos-platform --target aarch64-macos --output build/macos-platform-test --no-cache
file build/macos-platform-test | grep -q 'Mach-O 64-bit arm64 executable'
$DYN build tests/target-windows-platform --target x86_64-windows --output build/windows-platform-test --no-cache
file build/windows-platform-test | grep -q 'PE32+ executable.*x86-64'
$DYN build tests/empty --output build/cache-test >/dev/null
test "$($DYN build tests/empty --output build/cache-test)" = "cached build/cache-test"
mv tests/empty/main.dyn tests/empty/main.dyn.fast-cache-test
if $DYN build tests/empty --output build/cache-test --quiet >/dev/null 2>&1; then
  mv tests/empty/main.dyn.fast-cache-test tests/empty/main.dyn
  echo "expected removed source to invalidate fast cache" >&2
  exit 1
fi
mv tests/empty/main.dyn.fast-cache-test tests/empty/main.dyn
test "$($DYN build tests/empty --output build/cache-test --no-cache)" = "built build/cache-test"
test "$($DYN check tests/library)" = "ok"
$DYN build tests/shared-library --shared --output build/libdyn-shared-test.so \
  --release --quiet
file build/libdyn-shared-test.so | grep -q 'ELF 64-bit.*shared object'
readelf -Ws build/libdyn-shared-test.so | grep -q 'GLOBAL.*dyn_test_add'
cc tests/shared-library/caller.c -Lbuild -ldyn-shared-test \
  -Wl,-rpath,"$PWD/build" -o build/dyn-shared-caller
./build/dyn-shared-caller
$DYN build tests/shared-library --shared --target x86_64-windows \
  --output build/dyn-shared-test.dll --release --no-cache --quiet
file build/dyn-shared-test.dll | grep -q 'PE32+ executable.*DLL.*x86-64'
objdump -p build/dyn-shared-test.dll | grep -q 'dyn_test_add'
$DYN build tests/shared-library-consumer --target x86_64-windows \
  --output build/windows-shared-consumer --link build/dyn-shared-test.dll.a --no-cache --quiet
file build/windows-shared-consumer | grep -q 'PE32+ executable.*x86-64'
objdump -p build/windows-shared-consumer | grep -q 'dyn_test_add'
$DYN build tests/shared-library --shared --target aarch64-macos \
  --output build/libdyn-shared-test.dylib --release --no-cache --quiet
file build/libdyn-shared-test.dylib | grep -q 'Mach-O 64-bit arm64 dynamically linked shared library'
strings build/libdyn-shared-test.dylib | grep -q '_dyn_test_add'
$DYN build tests/shared-library-consumer --target aarch64-macos \
  --output build/macos-shared-consumer --link build/libdyn-shared-test.dylib --no-cache --quiet
file build/macos-shared-consumer | grep -q 'Mach-O 64-bit arm64 executable'
if $DYN run tests/shared-library --shared >build/run-shared.out 2>&1; then
  echo "expected run --shared conflict" >&2; exit 1
fi
grep -q 'run cannot be combined with --shared' build/run-shared.out
test "$($DYN run tests/stdlib-io --quiet)" = "$(printf 'std/io ok\nwarning: event count=3')"
$DYN build tests/stdlib-app --output build/stdlib-app-test --jobs 2 >/dev/null
./build/stdlib-app-test
cc -c tests/ffi/ffi_symbol.S -o build/cache-link-input.o
$DYN build tests/stdlib-app --output build/module-cache-test --jobs 2 >/dev/null
$DYN build tests/stdlib-app --output build/module-cache-test --jobs 2 \
  --link build/cache-link-input.o --verbose >build/module-cache.out 2>&1
grep -q 'cached module ' build/module-cache.out
grep -q 'cached interface ' build/module-cache.out
./build/module-cache-test
rm -rf build/shared-module-cache
rm -f build/shared-cache-a build/shared-cache-a.dyncache build/shared-cache-a.dyncache.files
rm -f build/shared-cache-b build/shared-cache-b.dyncache build/shared-cache-b.dyncache.files
mkdir -p build/shared-module-cache
DYN_CACHE_DIR=build/shared-module-cache $DYN build tests/stdlib-app --output build/shared-cache-a >/dev/null
DYN_CACHE_DIR=build/shared-module-cache $DYN build tests/stdlib-app --output build/shared-cache-b --verbose >build/shared-cache.out 2>&1
grep -q 'cached module ' build/shared-cache.out
$DYN build tests/net-protocol --output build/net-protocol-test >/dev/null
./build/net-protocol-test
$DYN build tests/websocket --output build/websocket-test >/dev/null
./build/websocket-test
$DYN build tests/stdlib-system --output build/stdlib-system-test >/dev/null
./build/stdlib-system-test
$DYN build tests/stdlib-os-expanded --output build/stdlib-os-expanded-test >/dev/null
./build/stdlib-os-expanded-test
$DYN build tests/stdlib-data --output build/stdlib-data-test >/dev/null
./build/stdlib-data-test
$DYN build tests/stdlib-depth --output build/stdlib-depth-test >/dev/null
./build/stdlib-depth-test
cc tests/deflate-zlib.c -lz -o build/deflate-zlib-test
$DYN build tests/deflate-encode --output build/deflate-encode-test >/dev/null
./build/deflate-encode-test | ./build/deflate-zlib-test
$DYN build tests/stdlib-foundation --output build/stdlib-foundation-test >/dev/null
./build/stdlib-foundation-test
$DYN build tests/json-dom --output build/json-dom-test >/dev/null
./build/json-dom-test
if $DYN run tests/empty --no-link >build/run-no-link.out 2>&1; then
  echo "expected run --no-link conflict" >&2
  exit 1
fi
grep -q "run cannot be combined with --no-link" build/run-no-link.out
$DYN check tests/empty >/dev/null
$DYN build tests/empty --output build/empty-test --emit-ir --emit-asm
./build/empty-test
test -s build/empty-test.ll
test -s build/empty-test.s

$DYN check tests/return >/dev/null
$DYN build tests/return --output build/return-test
./build/return-test

$DYN check tests/locals >/dev/null
$DYN build tests/locals --output build/locals-test --emit-ir
./build/locals-test

$DYN build tests/local-const --output build/local-const-test >/dev/null
./build/local-const-test
if $DYN check tests/local-const-errors >build/local-const-errors.out 2>&1; then
  echo "expected local constant diagnostics" >&2
  exit 1
fi
grep -q "local constant requires initializer" build/local-const-errors.out
grep -q "cannot assign to constant" build/local-const-errors.out
if $DYN check tests/grammar-feature-errors >build/grammar-feature-errors.out 2>&1; then
  echo "expected local type alias syntax diagnostic" >&2
  exit 1
fi
grep -q "local type aliases are not supported" build/grammar-feature-errors.out
if $DYN check tests/generic-type-syntax-errors >build/generic-type-syntax-errors.out 2>&1; then
  echo "expected parameterized type syntax diagnostics" >&2
  exit 1
fi
grep -q "invalid syntax" build/generic-type-syntax-errors.out
if $DYN check tests/generic-literal-syntax-errors >build/generic-literal-syntax-errors.out 2>&1; then
  echo "expected generic struct literal syntax diagnostics" >&2
  exit 1
fi
grep -q "invalid syntax" build/generic-literal-syntax-errors.out

$DYN check tests/expressions >/dev/null
$DYN build tests/expressions --output build/expressions-test --emit-ir
./build/expressions-test
grep -q "alloca i32" build/expressions-test.ll
grep -q "llvm.sadd.with.overflow.i32" build/expressions-test.ll

$DYN build tests/expressions --release --output build/expressions-release-test --emit-ir >/dev/null
./build/expressions-release-test
if grep -q "alloca" build/expressions-release-test.ll; then
  echo "release optimization failed to eliminate stack locals" >&2
  exit 1
fi

$DYN build tests/runtime-overflow --output build/runtime-overflow-test >/dev/null
set +e
./build/runtime-overflow-test
overflow_status=$?
set -e
test "$overflow_status" -eq 101

$DYN build tests/runtime-range-alias --output build/runtime-range-alias-debug-test --emit-ir >/dev/null
grep -q "llvm.uadd.with.overflow.i64" build/runtime-range-alias-debug-test.ll
$DYN build tests/runtime-range-alias --release --output build/runtime-range-alias-test --emit-ir >/dev/null
! grep -q "call void @dyn_trace_" build/runtime-range-alias-test.ll
$DYN build tests/large-array --release --output build/large-array-test --emit-ir >/dev/null
test "$(wc -c < build/large-array-test.ll)" -lt 100000
./build/large-array-test
$DYN build tests/large-array --output build/large-array-debug-test --emit-ir >/dev/null
test "$(wc -c < build/large-array-debug-test.ll)" -lt 100000
./build/large-array-debug-test
set +e
./build/runtime-range-alias-test
range_alias_status=$?
set -e
test "$range_alias_status" -eq 101

$DYN build benchmarks/language-profile/dyn --release --output build/range-optimization-test --emit-ir >/dev/null
./build/range-optimization-test
python3 tests/check-loop-ir.py build/range-optimization-test.ll

$DYN build tests/runtime-divzero --output build/runtime-divzero-test >/dev/null
set +e
./build/runtime-divzero-test
divzero_status=$?
set -e
test "$divzero_status" -eq 101

$DYN build tests/runtime-divoverflow --output build/runtime-divoverflow-test >/dev/null
set +e
./build/runtime-divoverflow-test
divoverflow_status=$?
set -e
test "$divoverflow_status" -eq 101

$DYN build tests/runtime-shift --output build/runtime-shift-test >/dev/null
set +e
./build/runtime-shift-test
shift_status=$?
set -e
test "$shift_status" -eq 101

$DYN build tests/short-circuit --output build/short-circuit-test >/dev/null
./build/short-circuit-test

$DYN check tests/conversions >/dev/null
$DYN build tests/conversions --output build/conversions-test --emit-ir >/dev/null
./build/conversions-test

$DYN check tests/distinct-types >/dev/null
$DYN build tests/distinct-types --output build/distinct-types-test --emit-ir >/dev/null
./build/distinct-types-test
grep -q "alloca i32" build/distinct-types-test.ll

if $DYN build tests/distinct-errors --output build/distinct-errors-test >build/distinct-errors.out 2>&1; then
  echo "expected nominal distinct-type errors" >&2
  exit 1
fi
test "$(grep -c "initializer type mismatch" build/distinct-errors.out)" -eq 3

if $DYN build tests/type-alias-cycle --output build/type-alias-cycle-test >build/type-alias-cycle.out 2>&1; then
  echo "expected type-alias cycle error" >&2
  exit 1
fi
grep -q "invalid or cyclic type alias" build/type-alias-cycle.out

$DYN build tests/process-arguments --output build/process-arguments-test >/dev/null
./build/process-arguments-test alpha beta

for stdlib_test in stdlib-process stdlib-testing stdlib-net-event stdlib-profile; do
  $DYN build tests/$stdlib_test --output build/$stdlib_test-test >/dev/null
  ./build/$stdlib_test-test
done
$DYN build tests/net-event-aarch64 --target aarch64-linux \
  --output build/stdlib-net-event-aarch64-test --no-link --no-cache >/dev/null
file build/stdlib-net-event-aarch64-test.o | grep -q 'ARM aarch64'

LIBC_PATH=$(${CC:-cc} -print-file-name=libc.so.6)
test -f "$LIBC_PATH"
$DYN build tests/stdlib-dynlib --output build/stdlib-dynlib-test --link "$LIBC_PATH" >/dev/null
./build/stdlib-dynlib-test

cc -fPIC -fno-stack-protector -c tests/stdlib-tls/provider.c -o build/stdlib-tls-provider.o
$DYN build tests/stdlib-tls --output build/stdlib-tls-test --link build/stdlib-tls-provider.o >/dev/null
./build/stdlib-tls-test

$DYN build tests/environment --output build/environment-test >/dev/null
DYN_STDLIB_ENV_TEST=value ./build/environment-test

$DYN build tests/stdlib-cli --output build/stdlib-cli-test >/dev/null
./build/stdlib-cli-test

$DYN build tests/stdlib-str --output build/stdlib-str-test >/dev/null
./build/stdlib-str-test

for stdlib_test in stdlib-mem-extra stdlib-text-extra stdlib-core-extra stdlib-reflect stdlib-c; do
  $DYN build tests/$stdlib_test --output build/$stdlib_test-test >/dev/null
  ./build/$stdlib_test-test
done

$DYN build tests/assert-message --output build/assert-message-test >/dev/null
set +e
./build/assert-message-test >build/assert-message.out 2>&1
assert_message_status=$?
set -e
test "$assert_message_status" -eq 101
grep -q "^custom assertion$" build/assert-message.out

$DYN build tests/directory-listing --output build/directory-listing-test >/dev/null
./build/directory-listing-test

cc -c tests/ffi/ffi_symbol.S -o build/ffi-symbol.o
cc -fno-stack-protector -c tests/ffi/ffi_variadic.c -o build/ffi-variadic.o
$DYN check tests/ffi >/dev/null
$DYN build tests/ffi --output build/ffi-test --link build/ffi-symbol.o \
  --link build/ffi-variadic.o --emit-ir >/dev/null
./build/ffi-test
grep -q "declare i64 @dyn_test_add(i64, i64)" build/ffi-test.ll
grep -q "declare i32 @dyn_test_variadic_sum(i32, ...)" build/ffi-test.ll
grep -q "call i32 (i32, ...) %.*(i32 3" build/ffi-test.ll

cc -fPIC -fno-stack-protector -c tests/ffi-library/library.c -o build/ffi-library.o
ar rcs build/libdyn-ffi-test.a build/ffi-library.o
$DYN build tests/ffi-library --output build/ffi-static-test \
  --link build/libdyn-ffi-test.a --quiet
./build/ffi-static-test
cc -shared -nostdlib build/ffi-library.o -o build/libdyn-ffi-test.so
$DYN build tests/ffi-library --output build/ffi-shared-test \
  --link "$PWD/build/libdyn-ffi-test.so" --quiet
./build/ffi-shared-test

if $DYN check tests/ffi-variadic-errors >build/ffi-variadic-errors.out 2>&1; then
  echo "expected foreign variadic ABI errors" >&2
  exit 1
fi
grep -q "function argument count mismatch" build/ffi-variadic-errors.out
grep -q "C variadic argument requires integer, float, or pointer" build/ffi-variadic-errors.out
grep -q "C variadic function requires a fixed parameter" build/ffi-variadic-errors.out

$DYN check tests/native-variadic >/dev/null
$DYN build tests/thread-aarch64 --target aarch64-linux --output build/thread-aarch64-test >/dev/null
if command -v qemu-aarch64 >/dev/null; then qemu-aarch64 ./build/thread-aarch64-test; fi
$DYN build tests/native-variadic --output build/native-variadic-test --emit-ir >/dev/null
./build/native-variadic-test
grep -q "define void @accept(ptr .*i64" build/native-variadic-test.ll
$DYN build tests/language-semantics-extended --output build/language-semantics-extended-test >/dev/null
./build/language-semantics-extended-test
if $DYN check tests/language-contract-errors >build/language-contract-errors.out 2>&1; then
  echo "expected language contract diagnostics" >&2
  exit 1
fi
grep -q "global any would escape borrowed storage" build/language-contract-errors.out
grep -q "returning any would escape borrowed storage" build/language-contract-errors.out
grep -q "dereference requires pointer" build/language-contract-errors.out
grep -q "indexing requires array or slice" build/language-contract-errors.out
grep -q "operator has mismatched types .* and .*; cast one operand" build/language-contract-errors.out
grep -q "any case requires _ arm" build/language-contract-errors.out
$DYN build tests/target --output build/target-test >/dev/null
./build/target-test

if $DYN check tests/ffi-errors >build/ffi-errors.out 2>&1; then
  echo "expected foreign ABI declaration errors" >&2
  exit 1
fi
grep -q "foreign link name must be a non-empty linker symbol" build/ffi-errors.out
grep -q "foreign parameter requires a concrete non-void type" build/ffi-errors.out
grep -q "duplicate foreign link symbol" build/ffi-errors.out
grep -q "foreign global requires a concrete non-void type" build/ffi-errors.out
grep -q "uitofp" build/conversions-test.ll
grep -q "fpext" build/conversions-test.ll

$DYN check tests/boundaries >/dev/null
$DYN build tests/boundaries --output build/boundaries-test --emit-ir >/dev/null
./build/boundaries-test
grep -q "fdiv" build/boundaries-test.ll

$DYN check tests/trailing-float >/dev/null
$DYN build tests/trailing-float --output build/trailing-float-test --emit-ir >/dev/null
./build/trailing-float-test
grep -q "2.000000e+00" build/trailing-float-test.ll

$DYN check tests/control-flow >/dev/null
$DYN build tests/control-flow --output build/control-flow-test --emit-ir >/dev/null
./build/control-flow-test
grep -q "if.then" build/control-flow-test.ll
grep -q "for.condition" build/control-flow-test.ll

$DYN build tests/control-flow-return --output build/control-flow-return-test --emit-ir >/dev/null
./build/control-flow-return-test
grep -q "unreachable" build/control-flow-return-test.ll

$DYN check tests/structs >/dev/null
$DYN build tests/structs --output build/structs-test --emit-ir >/dev/null
./build/structs-test
$DYN build tests/empty-struct --output build/empty-struct-test >/dev/null
./build/empty-struct-test
grep -q "type <{ i8, i32 }>" build/structs-test.ll
grep -q "literal.field.address" build/structs-test.ll
grep -q "getelementptr" build/structs-test.ll

for fixture in struct-errors struct-recursive struct-type-errors struct-duplicate-literal; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "duplicate struct declaration" build/struct-errors.out
grep -q "duplicate struct field" build/struct-errors.out
grep -q "struct contains itself by value" build/struct-recursive.out
grep -q "struct field initializer type mismatch" build/struct-type-errors.out
grep -q "field access requires struct or struct pointer" build/struct-type-errors.out
grep -q "duplicate struct literal field" build/struct-duplicate-literal.out

$DYN check tests/functions >/dev/null
$DYN build tests/functions --output build/functions-test --emit-ir >/dev/null
./build/functions-test
grep -q "define i32 @factorial" build/functions-test.ll
grep -q "call i32 @factorial" build/functions-test.ll
grep -q "define i64 @make_pair(i32" build/functions-test.ll
$DYN build tests/functions --release --output build/functions-release-test --emit-ir >/dev/null
./build/functions-release-test
grep -q "define internal .* @factorial" build/functions-release-test.ll

$DYN check tests/function-pointers >/dev/null
$DYN build tests/function-pointers --output build/function-pointers-test --emit-ir >/dev/null
./build/function-pointers-test
grep -q "indirect.call" build/function-pointers-test.ll
if $DYN check tests/function-pointer-errors >build/function-pointer-errors.out 2>&1; then
  echo "expected function pointer diagnostics" >&2
  exit 1
fi
grep -q "initializer type mismatch" build/function-pointer-errors.out
grep -q "function pointer argument count mismatch" build/function-pointer-errors.out
grep -q "call target must be function pointer" build/function-pointer-errors.out
$DYN build tests/runtime-nil-function --output build/runtime-nil-function-test >/dev/null
set +e
./build/runtime-nil-function-test
nil_function_status=$?
set -e
test "$nil_function_status" -eq 101

$DYN check tests/defer >/dev/null
$DYN build tests/defer --output build/defer-test --emit-ir >/dev/null
./build/defer-test
$DYN build tests/runtime-defer-loop --output build/runtime-defer-loop-test >/dev/null
./build/runtime-defer-loop-test
grep -q "defer.capture" build/defer-test.ll
if $DYN check tests/defer-errors >build/defer-errors.out 2>&1; then
  echo "expected defer diagnostics" >&2
  exit 1
fi
grep -q "deferred block cannot contain control transfer, declaration, or nested defer" build/defer-errors.out
$DYN build tests/runtime-panic-defer --output build/runtime-panic-defer-test --emit-ir >/dev/null
set +e
./build/runtime-panic-defer-test 2>build/runtime-panic-defer.err
panic_defer_status=$?
set -e
test "$panic_defer_status" -eq 101
test "$(cat build/runtime-panic-defer.err)" = "cleanup 3
cleanup 2
cleanup 1
expected
stack trace:
  at fail (tests/runtime-panic-defer/main.dyn:5)
  at middle (tests/runtime-panic-defer/main.dyn:10)
  at main (tests/runtime-panic-defer/main.dyn:15)"
grep -q "call void @cleanup" build/runtime-panic-defer-test.ll
$DYN build tests/runtime-panic-defer --release --output build/runtime-panic-defer-release-test >/dev/null
set +e
./build/runtime-panic-defer-release-test 2>build/runtime-panic-defer-release.err
panic_defer_release_status=$?
set -e
test "$panic_defer_release_status" -eq 101
test "$(cat build/runtime-panic-defer-release.err)" = "cleanup 3
cleanup 2
cleanup 1
expected"
$DYN build tests/runtime-double-panic --output build/runtime-double-panic-test >/dev/null
set +e
./build/runtime-double-panic-test 2>build/runtime-double-panic.err
double_panic_status=$?
set -e
test "$double_panic_status" -eq 101
grep -q "cleanup panic" build/runtime-double-panic.err
! grep -q "first panic" build/runtime-double-panic.err
if command -v readelf >/dev/null; then
  readelf -S build/runtime-panic-defer-test | grep -q '\.debug_info'
  readelf --debug-dump=decodedline build/runtime-panic-defer-test |
    grep -q 'tests/runtime-panic-defer/main.dyn'
fi
if command -v gdb >/dev/null; then
  gdb -q -nx -batch -ex 'set debuginfod enabled off' -ex 'break fail' -ex run \
    -ex bt build/runtime-panic-defer-test >build/runtime-panic-defer.gdb 2>&1
  grep -q 'fail () at tests/runtime-panic-defer/main.dyn:5' build/runtime-panic-defer.gdb
  grep -q 'middle () at tests/runtime-panic-defer/main.dyn:12' build/runtime-panic-defer.gdb
  grep -q 'main () at tests/runtime-panic-defer/main.dyn:17' build/runtime-panic-defer.gdb
fi
$DYN build tests/debug-info --debug --output build/debug-info-test >/dev/null
test "$(./build/debug-info-test)" = ""
if command -v readelf >/dev/null; then
  readelf --debug-dump=decodedline build/debug-info-test >build/debug-info.lines
  grep -q 'tests/debug-info/main.dyn' build/debug-info.lines
  grep -Eq '[[:space:]]2([[:space:]]|$)' build/debug-info.lines
  grep -Eq '[[:space:]]3([[:space:]]|$)' build/debug-info.lines
  grep -Eq '[[:space:]]4([[:space:]]|$)' build/debug-info.lines
  readelf --debug-dump=info build/debug-info-test >build/debug-info.info
  grep -q 'DW_TAG_variable' build/debug-info.info
  grep -q 'DW_AT_name.*base' build/debug-info.info
  grep -q 'DW_AT_name.*doubled' build/debug-info.info
  grep -q 'DW_AT_name.*result' build/debug-info.info
fi
if command -v gdb >/dev/null; then
  gdb -q -nx -batch -ex 'set debuginfod enabled off' \
    -ex 'break tests/debug-info/main.dyn:5' -ex run -ex 'print seed' -ex 'print base' \
    -ex 'print doubled' -ex 'print result' build/debug-info-test >build/debug-info.gdb 2>&1
  grep -Eq '\$[0-9]+ = 19' build/debug-info.gdb
  grep -Eq '\$[0-9]+ = 21' build/debug-info.gdb
  grep -Eq '\$[0-9]+ = 42' build/debug-info.gdb
  grep -Eq '\$[0-9]+ = 43' build/debug-info.gdb
fi
$DYN build tests/debug-info --release --output build/debug-info-release-test >/dev/null
if command -v readelf >/dev/null; then
  ! readelf -S build/debug-info-release-test | grep -q '\.debug_info'
fi
$DYN build tests/debug-optimized --release --debug-info \
  --output build/debug-optimized-test >/dev/null
if command -v readelf >/dev/null; then
  readelf -S build/debug-optimized-test | grep -q '\.debug_info'
  readelf --debug-dump=decodedline build/debug-optimized-test |
    grep -q 'tests/debug-optimized/main.dyn'
fi
if command -v gdb >/dev/null; then
  gdb -q -nx -batch -ex 'set debuginfod enabled off' -ex 'break compute' -ex run \
    -ex 'next' -ex 'print seed' -ex 'print value' -ex bt build/debug-optimized-test >build/debug-optimized.gdb 2>&1
  grep -q 'compute ' build/debug-optimized.gdb
  grep -q 'main ' build/debug-optimized.gdb
  grep -Eq '\$[0-9]+ = 19' build/debug-optimized.gdb
  grep -Eq '\$[0-9]+ = 20' build/debug-optimized.gdb
fi
$DYN build tests/debug-aggregates --debug --output build/debug-aggregates-test >/dev/null
if command -v readelf >/dev/null; then
  readelf --debug-dump=info build/debug-aggregates-test >build/debug-aggregates.info
  grep -q 'DW_AT_name.*Point' build/debug-aggregates.info
  grep -q 'DW_AT_name.*Node' build/debug-aggregates.info
  grep -q 'DW_AT_name.*Mode' build/debug-aggregates.info
  grep -q 'DW_AT_name.*Result' build/debug-aggregates.info
  grep -q 'DW_TAG_union_type' build/debug-aggregates.info
  grep -q 'DW_AT_name.*payload' build/debug-aggregates.info
  grep -q 'DW_AT_name.*values' build/debug-aggregates.info
  grep -q 'DW_AT_name.*debug_global' build/debug-aggregates.info
fi
if command -v gdb >/dev/null; then
  gdb -q -nx -batch -ex 'set debuginfod enabled off' \
    -ex 'break tests/debug-aggregates/main.dyn:30' -ex run \
    -ex 'print point.x' -ex 'print point.y' -ex 'print values[1]' \
    -ex 'print mode' -ex 'print node.value' -ex 'print node.next' \
    -ex 'print result.tag' -ex 'print result.payload.Ok' \
    -ex 'print debug_global' build/debug-aggregates-test \
    >build/debug-aggregates.gdb 2>&1
  grep -Eq '\$[0-9]+ = 20' build/debug-aggregates.gdb
  grep -Eq '\$[0-9]+ = 22' build/debug-aggregates.gdb
  grep -Eq '\$[0-9]+ = 5' build/debug-aggregates.gdb
  grep -Eq '(Busy|1)' build/debug-aggregates.gdb
  grep -Eq '\$[0-9]+ = 42' build/debug-aggregates.gdb
  grep -Eq '\$[0-9]+ = 77' build/debug-aggregates.gdb
fi

$DYN check tests/builtins >/dev/null
$DYN build tests/enum-pointer --output build/enum-pointer-test >/dev/null
./build/enum-pointer-test
$DYN check tests/cast-precedence >/dev/null
if $DYN check tests/source-map >build/source-map.out 2>&1; then
  echo "expected source-map diagnostic" >&2
  exit 1
fi
grep -q "tests/source-map/main.dyn:4:3: error: unreachable statement" build/source-map.out

if $DYN check tests/rewrite-source-map >build/rewrite-source-map.out 2>&1; then
  echo "expected rewritten source-map diagnostic" >&2
  exit 1
fi
grep -q "tests/rewrite-source-map/main.dyn:4:12: error: unknown name" build/rewrite-source-map.out
$DYN build tests/builtins --output build/builtins-test --emit-ir >/dev/null
./build/builtins-test
grep -q "call i64 @dyn_syscall6" build/builtins-test.ll
grep -q "bitcast" build/builtins-test.ll
if $DYN check tests/builtin-errors >build/builtin-errors.out 2>&1; then
  echo "expected builtin diagnostics" >&2
  exit 1
fi
grep -q "cannot cast .* to .*" build/builtin-errors.out
grep -q "#bitcast requires compatible scalar representation sizes" build/builtin-errors.out
grep -q "#sizeof requires sized value or type" build/builtin-errors.out
grep -q "#syscall requires syscall number and at most six arguments" build/builtin-errors.out
grep -q "#syscall arguments require integer or pointer" build/builtin-errors.out
grep -q "#panic message requires \[\]const u8" build/builtin-errors.out

$DYN check tests/stdlib-io >/dev/null
$DYN build tests/stdlib-io --output build/stdlib-io-test --emit-ir >/dev/null
test "$(./build/stdlib-io-test)" = "$(printf 'std/io ok\nwarning: event count=3')"
grep -q "dyn.string" build/stdlib-io-test.ll
(
  cd tests/stdlib-io
  ../../build/dyn check . >/dev/null
)

$DYN check tests/reflection >/dev/null
$DYN build tests/reflection --output build/reflection-test --emit-ir >/dev/null
./build/reflection-test
grep -q "dyn.string" build/reflection-test.ll
$DYN check tests/reflection-errors >/dev/null
$DYN build tests/reflection-errors --output build/reflection-no-std-test >/dev/null
./build/reflection-no-std-test

$DYN check tests/stdlib-runtime >/dev/null
$DYN build tests/stdlib-runtime --output build/stdlib-runtime-test --emit-ir >/dev/null
test "$(./build/stdlib-runtime-test)" = "std/runtime ok"
grep -q "call i64 @dyn_syscall6" build/stdlib-runtime-test.ll

$DYN check tests/stdlib-thread >/dev/null
$DYN build tests/stdlib-thread --output build/stdlib-thread-test >/dev/null
./build/stdlib-thread-test

$DYN check tests/memory-runtime >/dev/null
$DYN build tests/memory-runtime --output build/memory-runtime-test --emit-ir >/dev/null
test "$(./build/memory-runtime-test)" = "memory foundation ok"
grep -q "inttoptr" build/memory-runtime-test.ll
if $DYN check tests/pointer-slice-errors >build/pointer-slice-errors.out 2>&1; then
  echo "expected pointer slice diagnostic" >&2
  exit 1
fi
grep -q "pointer slicing requires explicit end bound" build/pointer-slice-errors.out

$DYN check compiler >/dev/null
$DYN build compiler --output build/dyn-demo --emit-ir >/dev/null
demo_output=$(./build/dyn-demo)
test "$demo_output" = "dyn demo
language: ok
memory: ok
reflection: ok
defer: second registered
defer: first registered
runtime: ok
demo complete"

for fixture in function-errors function-void-value; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "non-void function may exit without return" build/function-errors.out
grep -q "return type mismatch" build/function-errors.out
grep -q "return type mismatch (expected i32, found bool)" build/function-errors.out
grep -q "duplicate parameter name" build/function-errors.out
grep -q "unknown function" build/function-errors.out
grep -q "function argument count mismatch" build/function-errors.out
grep -q "function argument type mismatch" build/function-errors.out
grep -q "function argument type mismatch (expected i32, found bool)" build/function-errors.out
grep -q "discard non-void call result" build/function-errors.out
grep -q "local cannot have void type" build/function-void-value.out

$DYN check tests/pointers >/dev/null
$DYN build tests/pointers --output build/pointers-test --emit-ir >/dev/null
./build/pointers-test
$DYN build tests/pointer-array-field --output build/pointer-array-field-test >/dev/null
./build/pointer-array-field-test
grep -q "pointer.nonnull" build/pointers-test.ll
grep -q "pointer.aligned" build/pointers-test.ll
grep -q "getelementptr" build/pointers-test.ll

for fixture in pointer-const-errors pointer-type-errors; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "assignment through \*const pointer" build/pointer-const-errors.out
grep -q "initializer type mismatch" build/pointer-const-errors.out
grep -q "nil requires expected pointer type" build/pointer-type-errors.out
grep -q "address operand must be assignable storage" build/pointer-type-errors.out
grep -q "dereference requires pointer" build/pointer-type-errors.out
grep -q "arithmetic requires numeric operands" build/pointer-type-errors.out
grep -q "pointers support equality only" build/pointer-type-errors.out

$DYN build tests/runtime-nil-pointer --output build/runtime-nil-pointer-test >/dev/null
set +e
./build/runtime-nil-pointer-test
nil_pointer_status=$?
set -e
test "$nil_pointer_status" -eq 101

$DYN check tests/arrays >/dev/null
$DYN build tests/arrays --output build/arrays-test --emit-ir >/dev/null
./build/arrays-test
grep -q "\[4 x i32\]" build/arrays-test.ll
grep -q "slice.len" build/arrays-test.ll
grep -q "index.in.bounds" build/arrays-test.ll

$DYN build tests/optimizer-range --output build/optimizer-range-test --emit-ir >/dev/null
./build/optimizer-range-test
if grep -q "index.in.bounds" build/optimizer-range-test.ll; then
  echo "expected proven fixed-array loop access to omit bounds guard" >&2
  exit 1
fi
$DYN build tests/optimizer-range-unsafe --output build/optimizer-range-unsafe-test --emit-ir >/dev/null
grep -q "index.in.bounds" build/optimizer-range-unsafe-test.ll

$DYN build tests/optimizer-dominance --output build/optimizer-dominance-test --emit-ir >/dev/null
./build/optimizer-dominance-test
test "$(grep -Ec 'pointer.nonnull[^ ]* = icmp' build/optimizer-dominance-test.ll)" -eq 1
test "$(grep -Ec 'index.in.bounds[^ ]* = icmp' build/optimizer-dominance-test.ll)" -eq 1
$DYN build tests/optimizer-dominance-merge --output build/optimizer-dominance-merge-test --emit-ir >/dev/null
./build/optimizer-dominance-merge-test
test "$(grep -Ec 'pointer.nonnull[^ ]* = icmp' build/optimizer-dominance-merge-test.ll)" -eq 2
$DYN build tests/optimizer-dominance-call --output build/optimizer-dominance-call-test --emit-ir >/dev/null
./build/optimizer-dominance-call-test
test "$(grep -Ec 'pointer.nonnull[^ ]* = icmp' build/optimizer-dominance-call-test.ll)" -eq 3

$DYN check tests/pointer-iteration >/dev/null
$DYN build tests/pointer-iteration --output build/pointer-iteration-test --emit-ir >/dev/null
./build/pointer-iteration-test
grep -q "for.element" build/pointer-iteration-test.ll
if $DYN check tests/pointer-iteration-errors >build/pointer-iteration-errors.out 2>&1; then
  echo "expected pointer iteration diagnostics" >&2
  exit 1
fi
grep -q "pointer for-in over array requires assignable collection" build/pointer-iteration-errors.out
grep -q "mutable pointer for-in requires mutable collection" build/pointer-iteration-errors.out
grep -q "assignment through \*const pointer" build/pointer-iteration-errors.out

$DYN build tests/runtime-array-bounds --output build/runtime-array-bounds-test >/dev/null
set +e
./build/runtime-array-bounds-test
array_bounds_status=$?
set -e
test "$array_bounds_status" -eq 101

if $DYN check tests/array-errors >build/array-errors.out 2>&1; then
  echo "expected array diagnostics" >&2
  exit 1
fi
grep -q "empty array literal requires expected fixed-array type" build/array-errors.out
grep -q "array literal has too many elements" build/array-errors.out
grep -q "array element type mismatch" build/array-errors.out
grep -q "indexing requires array or slice" build/array-errors.out
grep -q "array index requires unsigned integer" build/array-errors.out
grep -q "aggregate values are not comparable" build/array-errors.out

$DYN check tests/enums >/dev/null
$DYN build tests/enums --output build/enums-test --emit-ir >/dev/null
./build/enums-test
grep -q "dyn.enum" build/enums-test.ll

$DYN check tests/multi-file >/dev/null
$DYN build tests/multi-file --output build/multi-file-test --emit-ir >/dev/null
./build/multi-file-test
grep -q "define i64 @make_point(i32" build/multi-file-test.ll

$DYN check tests/import-valid >/dev/null
$DYN build tests/import-valid --output build/import-valid-test >/dev/null
./build/import-valid-test
$DYN check tests/vendor-import >/dev/null
$DYN check tests/io-print >/dev/null
$DYN build tests/io-print --output build/io-print-test >/dev/null
./build/io-print-test
$DYN build tests/terminal-print --output build/terminal-print-test >/dev/null
./build/terminal-print-test >build/terminal-print.out
test "$(cat build/terminal-print.out)" = "terminal 42 true"
$DYN check tests/import-collisions >/dev/null
$DYN build tests/import-collisions --output build/import-collisions-test >/dev/null
./build/import-collisions-test
$DYN check tests/globals >/dev/null
$DYN build tests/globals --output build/globals-test --emit-ir >/dev/null
./build/globals-test
grep -q "define.*dyn_init" build/globals-test.ll
grep -q "@Answer = constant i32 42" build/globals-test.ll
grep -q "@Product = constant i32 42" build/globals-test.ll
grep -q "@Origin = constant %dyn.struct" build/globals-test.ll
grep -q "@Values = constant \[2 x i32\]" build/globals-test.ll
if grep -q "store.*@Answer" build/globals-test.ll; then
  echo "constant emitted through runtime initializer" >&2
  exit 1
fi
$DYN check tests/global-modules >/dev/null
$DYN build tests/global-modules --output build/global-modules-test --emit-ir >/dev/null
./build/global-modules-test
test "$(grep -c 'define.*__dyn_init_' build/global-modules-test.ll)" -eq 2
if $DYN check tests/global-errors >build/global-errors.out 2>&1; then
  echo "expected global diagnostics" >&2
  exit 1
fi
grep -q "constant requires initializer" build/global-errors.out
grep -q "constant initializer must be compile-time expression" build/global-errors.out
grep -q "cannot assign to constant" build/global-errors.out
if $DYN check tests/global-cycle >build/global-cycle.out 2>&1; then
  echo "expected global initialization cycle" >&2
  exit 1
fi
grep -q "global initialization cycle" build/global-cycle.out
$DYN check tests/import-duplicate-target >build/import-duplicate-target.out 2>&1
$DYN build tests/import-duplicate-target --output build/import-duplicate-target-test >/dev/null 2>&1
./build/import-duplicate-target-test
grep -q "imported more than once" build/import-duplicate-target.out

for fixture in import-cycle import-alias import-missing import-private import-unqualified import-unknown-alias; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "cyclic import" build/import-cycle.out
grep -q "duplicate import alias" build/import-alias.out
grep -q "does not resolve inside project root" build/import-missing.out
grep -q "missing or not pub" build/import-private.out
grep -q "must be module-qualified" build/import-unqualified.out
grep -q "unknown name" build/import-unknown-alias.out

if $DYN check tests/case-errors >build/case-errors.out 2>&1; then
  echo "expected case diagnostics" >&2
  exit 1
fi
grep -q "duplicate or overlapping case pattern" build/case-errors.out
grep -q "case is not exhaustive" build/case-errors.out
grep -q "_ case arm is unreachable" build/case-errors.out
grep -q "payloadless variant cannot bind payload" build/case-errors.out

if $DYN check tests/enum-errors >build/enum-errors.out 2>&1; then
  echo "expected enum diagnostics" >&2
  exit 1
fi
grep -q "enum tag type must be integer" build/enum-errors.out
grep -q "duplicate enum variant" build/enum-errors.out
grep -q "explicit enum discriminants are not supported" build/enum-errors.out
grep -q "enum payload type mismatch" build/enum-errors.out
grep -q "payload enum variant requires exactly one argument" build/enum-errors.out
grep -q "payloadless enum variant is not callable" build/enum-errors.out
grep -q "pointer payload binding requires mutable assignable case subject" build/enum-errors.out

for fixture in control-flow-errors control-flow-continue control-flow-scope control-flow-unreachable; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "control-flow condition requires bool" build/control-flow-errors.out
grep -q "break requires enclosing loop" build/control-flow-errors.out
grep -q "continue requires enclosing loop" build/control-flow-continue.out
if $DYN check tests/labeled-loop-errors >build/labeled-loop-errors.out 2>&1; then
  echo "expected labeled loop diagnostics" >&2
  exit 1
fi
grep -q "break requires enclosing loop" build/labeled-loop-errors.out
grep -q "duplicate active loop label" build/labeled-loop-errors.out
grep -q "note: previous label declared here \[range 6:3-6:7\]" build/labeled-loop-errors.out
grep -q "unknown active loop label" build/labeled-loop-errors.out
$DYN check tests/labeled-loops >/dev/null
$DYN build tests/labeled-loops --output build/labeled-loops-test --emit-ir >/dev/null
./build/labeled-loops-test
grep -q "assignment target is not declared" build/control-flow-scope.out
grep -q "unreachable statement" build/control-flow-unreachable.out

if $DYN check tests/lossy-conversion >build/lossy-conversion.out 2>&1; then
  echo "expected lossy implicit conversion error" >&2
  exit 1
fi
grep -q "initializer type mismatch" build/lossy-conversion.out
$DYN check tests/implicit-widening >/dev/null
$DYN build tests/implicit-widening --output build/implicit-widening-test >/dev/null
build/implicit-widening-test

for fixture in constant-divzero constant-overflow constant-shift; do
  if $DYN check "tests/$fixture" >"build/$fixture.out" 2>&1; then
    echo "expected $fixture diagnostic" >&2
    exit 1
  fi
done
grep -q "invalid constant division by zero" build/constant-divzero.out
grep -q "constant arithmetic overflows" build/constant-overflow.out
grep -q "invalid constant shift count" build/constant-shift.out

if $DYN check tests/local-errors >build/local-errors.out 2>&1; then
  echo "expected local assignment type error" >&2
  exit 1
fi
grep -q "assignment type mismatch" build/local-errors.out
grep -q "assignment type mismatch (expected i32, found bool).*\[range " build/local-errors.out


if $DYN check tests/invalid >build/invalid.out 2>&1; then
  echo "expected invalid syntax to fail" >&2
  exit 1
fi
grep -q "error: invalid syntax" build/invalid.out

if $DYN check tests/invalid-expression >build/invalid-expression.out 2>&1; then
  echo "expected bare expression statement to fail" >&2
  exit 1
fi
grep -q "error: invalid syntax" build/invalid-expression.out

if $DYN check tests/unsupported >build/unsupported.out 2>&1; then
  echo "expected unsupported semantics to fail" >&2
  exit 1
fi
grep -q "local type aliases are not supported" build/unsupported.out

if $DYN check tests/parser >build/parser.out 2>&1; then
  echo "expected parser fixture semantics to be unsupported" >&2
  exit 1
fi
if grep -q "invalid syntax" build/parser.out; then
  cat build/parser.out >&2
  exit 1
fi

DYN="$DYN" ./tests/source-limits.sh

$DYN check tests/local-errors --diagnostics json >build/diagnostic-json.out 2>&1 || true
grep -q '^{"severity":"error".*"range":' build/diagnostic-json.out
$DYN check tests/manifest-app >/dev/null
$DYN docs compiler/std/sort >build/sort-docs.md
grep -q 'pub fn search_i64' build/sort-docs.md
$DYN fmt --check tests/empty
DYN="$DYN" python3 tests/lsp-contracts.py
DYN="$DYN" python3 tests/lsp.py
DYN="$DYN" python3 tests/lsp-completion.py
DYN="$DYN" python3 tests/lsp-index.py
DYN="$DYN" python3 tests/lsp-project.py

echo "all tests passed"

$DYN build tests/import-field-collision --output build/import-field-collision-test --quiet
./build/import-field-collision-test
$DYN build tests/stdlib-contracts --output build/stdlib-contracts --quiet
./build/stdlib-contracts

# Reflection can grow AST/type tables while checking a containing expression.
$DYN build tests/sema-table-growth --no-cache --quiet --output build/sema-table-growth
./build/sema-table-growth
$DYN build tests/sema-table-growth --release --no-cache --quiet --output build/sema-table-growth-release
./build/sema-table-growth-release
DYN="$DYN" python3 tests/compiler-diagnostics.py

# Fixed-size expression temporaries must not accumulate on loop iterations.
$DYN build tests/loop-stack --no-cache --quiet --output build/loop-stack
./build/loop-stack
$DYN build tests/loop-stack --release --no-cache --quiet --output build/loop-stack-release
./build/loop-stack-release
