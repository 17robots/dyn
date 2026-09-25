#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

results=build/bench/results.tsv
mkdir -p build/bench
CC=${CC:-clang} ./benchmarks/run.sh "${1:-21}" > "$results"
cat "$results"

awk -F '\t' '
  $1 == "compute/dyn" { compute_dyn=$2 }
  $1 == "compute/c" { compute_c=$2 }
  $1 == "arena/dyn" { arena_dyn=$2; dyn_size=$6 }
  $1 == "arena/c-matched" { arena_c=$2; c_size=$6 }
  $1 == "format/dyn" { format_dyn=$2 }
  $1 == "format/c-matched" { format_c=$2 }
  $1 == "io-lines/dyn" { io_dyn=$2 }
  $1 == "io-lines/c-matched" { io_c=$2 }
  END {
    failed = 0
    if (compute_dyn > compute_c * 1.10) { print "compute regression" > "/dev/stderr"; failed=1 }
    # C omits per-push Dyn bounds, alignment, and checked-arithmetic contract.
    if (arena_dyn > arena_c * 3.00) { print "arena regression (>3x checked C)" > "/dev/stderr"; failed=1 }
    if (format_dyn > format_c * 1.10) { print "format regression" > "/dev/stderr"; failed=1 }
    if (io_dyn > io_c * 1.50) { print "stream I/O regression" > "/dev/stderr"; failed=1 }
    # Dyn output is static/libc-free; C is dynamically linked, so use a
    # stable absolute budget instead of pretending their file sizes are peers.
    if (dyn_size > 65536) { print "static Dyn size regression (>64 KiB)" > "/dev/stderr"; failed=1 }
    exit failed
  }
' "$results"
