#!/bin/sh
set -eu
DYN=${DYN:-./build/dyn}
root=build/source-limit-test
mkdir -p "$root"
truncate -s 67108865 "$root/main.dyn"
if "$DYN" check "$root" >build/source-limit.out 2>&1; then
  echo "expected source-size diagnostic" >&2
  exit 1
fi
grep -q "exceeds 64 MiB limit" build/source-limit.out
