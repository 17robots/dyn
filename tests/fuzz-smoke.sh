#!/bin/sh
# Deterministic parser/checker/runtime fuzz smoke. Use a sanitized DYN to turn
# compiler memory and undefined-behavior findings into failures.
set -eu
cd "$(dirname "$0")/.."
dyn=${DYN:-./build/dyn}
root=build/fuzz-smoke
mkdir -p "$root/case"
rm -f "$root/case/bindings.dyn"
seed=${DYN_FUZZ_SEED:-1}
cases=${DYN_FUZZ_CASES:-96}
case "$seed:$cases" in *[!0-9:]*) echo "DYN_FUZZ_SEED and DYN_FUZZ_CASES must be integers" >&2; exit 2;; esac

check_source() {
  printf '%s' "$1" > "$root/case/main.dyn"
  set +e
  "$dyn" check "$root/case" >"$root/check.log" 2>&1
  status=$?
  set -e
  if grep -Eq 'Sanitizer|runtime error:' "$root/check.log"; then
    cp "$root/case/main.dyn" "$root/sanitizer-$seed-${i:-static}.dyn"
    cat "$root/check.log" >&2
    exit 1
  fi
  case "$status" in 0|1) ;; *)
    case_number=${i:-static}
    cp "$root/case/main.dyn" "$root/failure-$seed-$case_number.dyn"
    echo "compiler crashed; saved $root/failure-$seed-$case_number.dyn (seed=$seed case=$case_number)" >&2
    exit 1;;
  esac
}

check_source ''
check_source 'fn main( {'
check_source 'fn main() { value := [][[[ }'
check_source '#target(os: unlikely) fn main() {}'
check_source 'fn main() { case 1 { 0..18446744073709551615 => {}, _ => {} } }'
check_source 'fn main() { text := "unterminated'

# Generated token soup exercises parser recovery and checker error paths.
tokens='fn main ( ) { } value := 0 true false + - * / [ ] case _ => return rawptr any'
i=0
while test "$i" -lt "$cases"; do
  source=''
  j=0
  state=$((i + seed))
  while test "$j" -lt 24; do
    state=$(((state * 1103515245 + 12345) & 2147483647))
    pick=$((state % 23 + 1))
    token=$(printf '%s\n' "$tokens" | awk -v n="$pick" '{ print $n }')
    source="$source $token"
    j=$((j + 1))
  done
  check_source "$source"
  i=$((i + 1))
done

# Valid generated program reaches checker, LLVM, linker, and runtime. Shell
# arithmetic independently calculates expected result.
runtime_source='fn main() {
  value: i64 = 7'
expected=7
i=1
while test "$i" -le 32; do
  operand=$(((i * 17 + 3) % 29 + 1))
  case $((i % 3)) in
    0) runtime_source="$runtime_source
  value += $operand"; expected=$((expected + operand)) ;;
    1) runtime_source="$runtime_source
  value = value + $operand"; expected=$((expected + operand)) ;;
    2) runtime_source="$runtime_source
  value = value * 3 - $operand"; expected=$((expected * 3 - operand)) ;;
  esac
  i=$((i + 1))
done
runtime_source="$runtime_source
  if value != $expected { #panic(\"runtime fuzz mismatch\") }
}"
printf '%s\n' "$runtime_source" > "$root/case/main.dyn"
"$dyn" build "$root/case" --output "$root/runtime" --no-cache --quiet
"$root/runtime"

# Debug and optimized code generation must agree on a generated observable exit
# status. This catches optimizer-only lowering mistakes without an oracle tied to
# compiler internals.
printf '%s\n' "$runtime_source" > "$root/case/main.dyn"
"$dyn" build "$root/case" --output "$root/runtime-debug" --no-cache --quiet
"$dyn" build "$root/case" --output "$root/runtime-release" --release --no-cache --quiet
"$root/runtime-debug"; debug_status=$?
"$root/runtime-release"; release_status=$?
test "$debug_status" -eq "$release_status" || {
  cp "$root/case/main.dyn" "$root/differential-$seed.dyn"
  echo "debug/release mismatch; saved $root/differential-$seed.dyn" >&2; exit 1;
}

# Exercise C declaration extraction with a deterministic family of legal
# headers, then parse/check every generated Dyn binding.
bind=${DYN_BIND:-tools/dyn-bind.py}
mkdir -p "$root/bind"
i=0
while test "$i" -lt 24; do
  value=$(((seed + i * 37) % 10000))
  header="$root/bind/case-$i.h"
  output="$root/bind/case-$i.dyn"
  printf '#define DYN_FUZZ_%s %s\ntypedef struct DynFuzz%s { int x; unsigned char flag; } DynFuzz%s;\nenum DynFuzzEnum%s { DYN_FUZZ_A%s = %s, DYN_FUZZ_B%s };\nint dyn_fuzz_%s(const DynFuzz%s *value, int (*callback)(int));\n' \
    "$i" "$value" "$i" "$i" "$i" "$i" "$value" "$i" "$i" "$i" > "$header"
  python3 "$bind" "$header" -o "$output"
  cp "$output" "$root/case/bindings.dyn"
  printf 'fn main() {}\n' > "$root/case/main.dyn"
  "$dyn" check "$root/case" --quiet
  rm -f "$root/case/bindings.dyn"
  i=$((i + 1))
done
echo 'fuzz smoke passed'
