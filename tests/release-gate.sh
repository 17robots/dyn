#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export DYN=${DYN:-"$PWD/build/dyn-release"}
python3 tests/reproducible-builds.py
./benchmarks/compile-scale/run.sh > build/compile-scale.tsv
awk 'NR > 1 && $3 >= 100000 { exit 1 }' build/compile-scale.tsv
echo 'release gate passed'
