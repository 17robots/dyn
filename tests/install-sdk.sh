#!/bin/sh
set -eu
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
DESTDIR="$root" PREFIX=/sdk just install >/dev/null
test "$($root/sdk/bin/dyn --version)" = "dyn ${DYN_VERSION:-0.1.0-dev}"
cd /tmp
"$root/sdk/bin/dyn" check "$OLDPWD/tests/lsp-public-struct" --quiet
"$root/sdk/bin/dyn" check "$OLDPWD/tests/vendor-import" --quiet
"$root/sdk/bin/dyn" build "$OLDPWD/tests/empty" --release --output "$root/empty" --quiet
"$root/empty"
echo 'installed SDK passed'
