#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
runs=${1:-15}
mkdir -p build/bench
cc -O2 -Wall -Wextra -Werror benchmarks/runner.c -o build/bench/runner
./build/dyn build benchmarks/compute --release --output build/bench/compute-dyn >/dev/null
cc -O2 -Wall -Wextra -Werror benchmarks/compute/main.c -o build/bench/compute-c
implementations='dyn build/bench/compute-dyn c build/bench/compute-c'
if command -v go >/dev/null 2>&1; then go build -trimpath -ldflags='-s -w' -o build/bench/compute-go benchmarks/compute/main.go; implementations="$implementations go build/bench/compute-go"; fi
if command -v zig >/dev/null 2>&1; then zig build-exe -O ReleaseFast -fstrip -femit-bin=build/bench/compute-zig benchmarks/compute/main.zig; implementations="$implementations zig build/bench/compute-zig"; fi
if command -v odin >/dev/null 2>&1; then odin build benchmarks/compute/main.odin -file -o:speed -out:build/bench/compute-odin; implementations="$implementations odin build/bench/compute-odin"; fi
expected=$(build/bench/compute-dyn)
printf 'implementation\tmedian_wall_s\tuser_s\tsystem_s\tpeak_rss_kib\tstripped_bytes\n'
set -- $implementations
while test "$#" -gt 0; do name=$1 executable=$2; shift 2; test "$($executable 2>&1)" = "$expected"; build/bench/runner "$runs" /dev/null "compute/$name" "$executable"; done
