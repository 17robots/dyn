#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

runs=${1:-15}
bench_cc=${CC:-cc}
mkdir -p build/bench
"$bench_cc" -O2 -Wall -Wextra -Werror benchmarks/runner.c -o build/bench/runner

build_pair() {
  name=$1
  ./build/dyn build "benchmarks/$name" --release --output "build/bench/$name-dyn" >/dev/null
  "$bench_cc" -O2 -Wall -Wextra -Werror "benchmarks/$name/main.c" -o "build/bench/$name-c"
  strip -s "build/bench/$name-dyn" "build/bench/$name-c"
}

build_pair startup
build_pair compute
build_pair arena
./build/dyn build benchmarks/format --release --output build/bench/format-dyn >/dev/null
"$bench_cc" -O2 -Wall -Wextra -Werror benchmarks/format/matched.c -o build/bench/format-matched
"$bench_cc" -O2 -Wall -Wextra -Werror benchmarks/format/stdio.c -o build/bench/format-stdio
./build/dyn build benchmarks/io-lines --release --output build/bench/io-lines-dyn >/dev/null
"$bench_cc" -O2 -Wall -Wextra -Werror benchmarks/io-lines/matched.c -o build/bench/io-lines-matched
"$bench_cc" -O2 -Wall -Wextra -Werror benchmarks/io-lines/stdio.c -o build/bench/io-lines-stdio
strip -s build/bench/*-dyn build/bench/format-matched build/bench/format-stdio \
  build/bench/io-lines-matched build/bench/io-lines-stdio

awk 'BEGIN { for (i=0; i<1000000; ++i) print "add benchmark line " i }' > build/bench/input.txt
: > build/bench/empty.txt

same() {
  input=$1; shift
  expected=$($1 < "$input")
  for executable in "$@"; do
    actual=$($executable < "$input")
    if [ "$actual" != "$expected" ]; then
      echo "checksum mismatch: $executable: $actual != $expected" >&2; exit 1
    fi
  done
}
same build/bench/empty.txt build/bench/compute-dyn build/bench/compute-c
same build/bench/empty.txt build/bench/arena-dyn build/bench/arena-c
same build/bench/empty.txt build/bench/format-dyn build/bench/format-matched build/bench/format-stdio
same build/bench/input.txt build/bench/io-lines-dyn build/bench/io-lines-matched build/bench/io-lines-stdio

printf 'implementation\tmedian_wall_s\tuser_s\tsystem_s\tpeak_rss_kib\tstripped_bytes\n'
bench() { build/bench/runner "$runs" "$1" "$2" "$3"; }
bench build/bench/empty.txt startup/dyn build/bench/startup-dyn
bench build/bench/empty.txt startup/c-dynamic build/bench/startup-c
bench build/bench/empty.txt compute/dyn build/bench/compute-dyn
bench build/bench/empty.txt compute/c build/bench/compute-c
bench build/bench/empty.txt arena/dyn build/bench/arena-dyn
bench build/bench/empty.txt arena/c-matched build/bench/arena-c
bench build/bench/empty.txt format/dyn build/bench/format-dyn
bench build/bench/empty.txt format/c-matched build/bench/format-matched
bench build/bench/empty.txt format/c-stdio build/bench/format-stdio
bench build/bench/input.txt io-lines/dyn build/bench/io-lines-dyn
bench build/bench/input.txt io-lines/c-matched build/bench/io-lines-matched
bench build/bench/input.txt io-lines/c-stdio build/bench/io-lines-stdio
