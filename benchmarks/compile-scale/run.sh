#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."

mkdir -p build/bench/compile-scale/source
printf 'bytes: [SIZE]u8 = []\nfn main() { bytes[0] = 1 }\n' \
  > build/bench/compile-scale/template.dyn

printf 'array_bytes\telapsed_ms\tir_bytes\n'
for bytes in 1024 1048576 67108864; do
  sed "s/SIZE/$bytes/" build/bench/compile-scale/template.dyn \
    > build/bench/compile-scale/source/main.dyn
  start=$(date +%s%N)
  "${DYN:-./build/dyn}" build build/bench/compile-scale/source --release \
    --output build/bench/compile-scale/program --emit-ir >/dev/null
  end=$(date +%s%N)
  elapsed=$(((end - start) / 1000000))
  ir_bytes=$(wc -c < build/bench/compile-scale/program.ll)
  printf '%s\t%s\t%s\n' "$bytes" "$elapsed" "$ir_bytes"
done
