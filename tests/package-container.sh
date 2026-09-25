#!/usr/bin/env bash
# Qualify the actual archive without any installed compiler toolchain.
set -euo pipefail
archive=$(realpath "$1")
version=$2
root=$(cd "$(dirname "$0")/.." && pwd)
engine=${CONTAINER_ENGINE:-docker}
for image in ubuntu:24.04 archlinux:base; do
  "$engine" run --rm --network none --tmpfs /tmp:exec \
    -v "$archive:/sdk.tar.gz:ro" -v "$root/tests/smoke:/smoke:ro" \
    "$image" bash -eu -c '
      export PATH=/usr/bin:/bin
      unset DYN_SDK LD_LIBRARY_PATH
      ! command -v ld.lld
      mkdir -p "/tmp/relocated sdk"
      tar -xzf /sdk.tar.gz -C "/tmp/relocated sdk"
      dyn="/tmp/relocated sdk/dyn-sdk/bin/dyn"
      test "$("$dyn" version)" = "dyn $1"
      ldd "$dyn"
      export DYN_CACHE_DIR=/tmp/cache
      "$dyn" build /smoke --no-cache --quiet --output /tmp/smoke-debug
      /tmp/smoke-debug
      ln -s "$dyn" /tmp/dyn
      /tmp/dyn build /smoke --release --no-cache --quiet --output /tmp/smoke-release
      /tmp/smoke-release
      echo "PASS clean container: $2"
    ' bash "$version" "$image"
done
